"""A9 — Web API ve sayfalar.

Akış: e-posta ile tek kullanımlık giriş → .docx yükle → bellekte, ayrı süreçte denetim →
rapor ekranı. Tez dosyası diske yazılmaz; rapor saklama süresi sonunda silinir.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import smtplib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from synora.check import USER_ROLES
from synora.errors import ErrorCode
from synora.latex import build_zip
from synora.log import log_event
from synora.report import ROLE_NAMES, SEVERITY_NAMES, ingest_message
from synora.ruleset import Ruleset, load_ruleset
from synora.web.db import Database, Job
from synora.web.mailer import Mailer, make_mailer
from synora.web.presentation import PageSpec, RuleTile, page_spec, pixel_blocks, rule_tiles
from synora.web.settings import Settings
from synora.web.worker import JobRunner

HERE = Path(__file__).resolve().parent
SESSION_COOKIE = "synora_session"
PRE_CSRF_COOKIE = "synora_pre"
# Kayıtta onaylanan aydınlatma metninin sürümü; metin değişince artırılır.
TERMS_VERSION = "aydinlatma-taslak-2026-10"
SERVER_BUSY = "Sunucu şu an yoğun. Bir dakika sonra yeniden deneyin."
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}")
JOB_ID_RE = re.compile(r"[A-Za-z0-9_\-]{16,64}")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)
OUTPUT_FILES = {"fixed": "synora-duzeltilmis.docx", "annotated": "synora-yorumlu.docx"}
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OUTPUT_ERRORS = {
    "NOTHING_TO_FIX": "Bu belgede otomatik düzeltilebilecek bir bulgu yok.",
    "TIMEOUT": "İşlem süre sınırını aştı. Raporu kullanarak Word'de düzeltebilirsiniz.",
}
MAX_USER_ROLES = 2000
# Rol seçim listesi (arayüz sırası); yalnızca synora.check.USER_ROLES içindekiler.
ROLE_CHOICES = [r for r in (
    "heading_1", "heading_2", "heading_3", "body", "front_matter", "block_quote", "list_item",
    "figure_caption", "table_caption", "reference_entry") if r in {u.value for u in USER_ROLES}]
JOB_ERRORS = {
    "TIMEOUT": "Denetim süre sınırını aştı. Belge çok büyük ya da karmaşık olabilir.",
    "INTERNAL": "Beklenmeyen bir hata oluştu. Dosyanızı Word'de açıp yeniden kaydedip deneyin.",
    "INTERRUPTED": "Sunucu yeniden başlatıldığı için denetim tamamlanamadı. Yeniden yükleyin.",
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class User:
    email: str
    csrf: str
    session_hash: str


@dataclass(frozen=True)
class RulesetInfo:
    id: str
    name: str
    path: Path
    rules: Ruleset


def discover_rulesets(directory: Path) -> dict[str, RulesetInfo]:
    found: dict[str, RulesetInfo] = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            rules = load_ruleset(path)
        except (ValidationError, OSError, ValueError):
            continue
        found[rules.ruleset] = RulesetInfo(rules.ruleset, rules.name, path, rules)
    return found


# Türk alfabesi: Ç, Ğ, I/İ, Ö, Ş, Ü yerinde sıralansın (Python varsayılanı bunları sona atar).
_TR_ALPHABET = "abcçdefgğhıijklmnoöprsştuüvyz"
_TR_FOLD = str.maketrans({"I": "ı", "İ": "i", "â": "a", "Â": "a", "î": "i", "Î": "i",
                          "û": "u", "Û": "u"})


def tr_sort_key(text: str) -> tuple[int, ...]:
    key: list[int] = []
    for ch in text.translate(_TR_FOLD).lower():
        pos = _TR_ALPHABET.find(ch)
        # Boşluk ve rakamlar harflerden önce, alfabe dışı harfler sonra.
        key.append(pos if pos >= 0 else (100 + ord(ch) if ch.isalpha() else ord(ch) - 1000))
    return tuple(key)


@dataclass(frozen=True)
class RulesetGroup:
    institution: str
    items: list[RulesetInfo]


OTHER_GROUP = "Diğer"


def order_rulesets(rulesets: dict[str, RulesetInfo], default: str) -> list[RulesetInfo]:
    """Varsayılan kılavuz başta, örnek kural seti sonda, kalanlar Türkçe alfabetik."""
    return sorted(rulesets.values(), key=lambda r: (
        r.id != default, r.id == "example", tr_sort_key(r.name)))


def group_rulesets(ordered: list[RulesetInfo]) -> list[RulesetGroup]:
    groups: dict[str, list[RulesetInfo]] = {}
    for r in ordered:
        groups.setdefault(r.rules.institution or OTHER_GROUP, []).append(r)
    names = sorted(groups, key=lambda n: (n == OTHER_GROUP, tr_sort_key(n)))
    return [RulesetGroup(n, sorted(groups[n], key=lambda r: tr_sort_key(r.name))) for n in names]


def job_error_message(code: str | None) -> str:
    if code in JOB_ERRORS:
        return JOB_ERRORS[code]
    try:
        return ingest_message(ErrorCode(code or ""))
    except ValueError:
        return JOB_ERRORS["INTERNAL"]


TR_TZ = timezone(timedelta(hours=3))  # Türkiye 2016'dan beri yaz saati uygulamıyor
TR_MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


TR_MONTHS_LONG = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
                  "Eylül", "Ekim", "Kasım", "Aralık"]


def format_date(ts: float) -> str:
    """LaTeX'teki bugünün tarihi biçimi: '12 Ekim 2026'."""
    d = datetime.fromtimestamp(ts, TR_TZ)
    return f"{d.day} {TR_MONTHS_LONG[d.month - 1]} {d.year}"


def format_when(ts: float) -> str:
    d = datetime.fromtimestamp(ts, TR_TZ)
    return f"{d.day} {TR_MONTHS[d.month - 1]} {d:%H:%M}"


def applied_roles(report: dict[str, Any]) -> dict[str, str]:
    return dict(report.get("user_roles") or {})


def pending_roles(job: Job, report: dict[str, Any]) -> dict[str, str]:
    """Öğrencinin şu anki seçimleri: kaydedilmiş seçim yoksa rapora uygulanmış olanlar."""
    return dict(json.loads(job.user_roles)) if job.user_roles is not None else applied_roles(report)


def report_view(report: dict[str, Any]) -> dict[str, Any]:
    """Rapor JSON'unu ekran için gruplar: aynı kural + aynı değerler tek kart."""
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for f in report["findings"]:
        key = (f["rule_id"], f["expected"], f["actual"])
        g = groups.get(key)
        if g is None:
            role = f.get("role")
            g = groups[key] = {
                "message": f["message"],
                "severity": f["severity"],
                "severity_name": SEVERITY_NAMES.get(f["severity"], f["severity"]),
                "role_name": _role_name(role),
                "fixable": f["fixable"],
                "rule_id": f["rule_id"],
                "locations": [],
                "sections": set(),
                "count": 0,
            }
        g["count"] += 1
        if f.get("location"):
            g["locations"].append(f["location"])
        elif f.get("section_index") is not None:
            g["sections"].add(f["section_index"] + 1)
        g.setdefault("blocks", set())
        if f.get("block") is not None:
            g["blocks"].add(f["block"])
    order = {"error": 0, "warning": 1, "info": 2}
    # Editörde yorumlar belge sırasını izler (Word'ün gözden geçirme bölmesi gibi).
    cards = sorted(
        groups.values(),
        key=lambda g: (min(g["blocks"]) if g["blocks"] else -1, order.get(g["severity"], 9)),
    )
    blocks: list[dict[str, Any]] = [dict(b) for b in report.get("document") or []]
    for b in blocks:
        b["cards"], b["sev"] = [], None
    for n, c in enumerate(cards, start=1):
        c["n"] = n
        c["sections"] = sorted(c["sections"])
        c["blocks"] = sorted(c["blocks"])
        for i in c["blocks"]:
            if 0 <= i < len(blocks):
                blocks[i]["cards"].append(n)
                if blocks[i]["sev"] != "error":
                    blocks[i]["sev"] = c["severity"]
    return {"summary": report["summary"], "ruleset": report["ruleset"], "cards": cards,
            "finding_count": len(report["findings"]), "blocks": blocks, "outline": _outline(blocks),
            "role_choices": [(r, _role_name(r)) for r in ROLE_CHOICES],
            "editable": sum(1 for b in blocks if "pid" in b)}


def _outline(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sol bölme: bölümler ve başlıklar; her girdinin kapsadığı bloklardaki bulgu sayısı."""
    entries: list[dict[str, Any]] = []
    for i, b in enumerate(blocks):
        if b["kind"] in ("h1", "h2", "h3", "section"):
            entries.append({"i": i, "kind": b["kind"],
                            "text": b.get("text") or f"Bölüm {b.get('n')}"})
    for k, e in enumerate(entries):
        end = entries[k + 1]["i"] if k + 1 < len(entries) else len(blocks)
        e["count"] = len({n for b in blocks[e["i"]:end] for n in b["cards"]})
    return entries


def _role_name(role: str | None) -> str:
    if not role:
        return ""
    from synora.model import Role

    try:
        return ROLE_NAMES.get(Role(role), "")
    except ValueError:
        return ""


def create_app(settings: Settings | None = None, mailer: Mailer | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    problems = settings.problems()
    if problems:
        raise RuntimeError("Üretim ayarları eksik ya da güvensiz: " + "; ".join(problems))
    db = Database(settings.db_path)
    mailer = mailer or make_mailer(settings)
    runner = JobRunner(db, settings)
    rulesets = discover_rulesets(settings.rulesets_dir)
    # Varsayılan (pilot) kılavuz başta: giriş sayfası onu tanıtır, yüklemede seçili gelir.
    ordered_rulesets = order_rulesets(rulesets, settings.default_ruleset)
    ruleset_groups = group_rulesets(ordered_rulesets)
    login_page: PageSpec | None = (
        page_spec(ordered_rulesets[0].rules) if ordered_rulesets else None
    )
    login_tiles: list[RuleTile] = rule_tiles(ordered_rulesets[0].rules) if ordered_rulesets else []
    # LaTeX şablonu ilk istendiğinde kural setinden üretilip saklanır (kullanıcı girdisi yok;
    # yalnızca keşfedilmiş kural seti kimlikleri kabul edilir).
    latex_zips: dict[str, bytes] = {}
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["when"] = format_when
    templates.env.filters["date_tr"] = format_date
    templates.env.globals["now"] = time.time
    templates.env.globals["hero_blocks"] = pixel_blocks()
    # Statik dosyalar için sürüm damgası: içerik değişince tarayıcı önbelleği geçersizleşir.
    asset_hash = hashlib.sha256()
    for name in ("app.css", "app.js", "fonts.css"):
        asset_hash.update((HERE / "static" / name).read_bytes())
    templates.env.globals["asset_v"] = asset_hash.hexdigest()[:10]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db.purge(settings.retention_hours * 3600)
        runner.start()
        yield
        runner.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db = db
    app.state.runner = runner
    app.state.mailer = mailer
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        h = response.headers
        h["Content-Security-Policy"] = CSP
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "no-referrer"
        h["X-Frame-Options"] = "DENY"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        if not request.url.path.startswith("/static"):
            h["Cache-Control"] = "no-store"
        if settings.secure_cookies:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # --- Yardımcılar -----------------------------------------------------------------------

    def current_user(request: Request) -> User | None:
        sid = request.cookies.get(SESSION_COOKIE)
        if not sid:
            return None
        sid_hash = _hash(sid)
        found = db.get_session(sid_hash)
        if found is None:
            return None
        return User(email=found[0], csrf=found[1], session_hash=sid_hash)

    def require_user(request: Request) -> User:
        user = current_user(request)
        if user is None:
            raise HTTPException(401)
        return user

    def check_csrf(expected: str, provided: str | None) -> None:
        if not provided or not hmac.compare_digest(expected, provided):
            raise HTTPException(403, "CSRF")

    def pre_csrf(request: Request) -> str:
        return request.cookies.get(PRE_CSRF_COOKIE) or secrets.token_urlsafe(24)

    def set_pre_csrf(response: Response, token: str) -> None:
        response.set_cookie(PRE_CSRF_COOKIE, token, httponly=True, samesite="strict",
                            secure=settings.secure_cookies, max_age=3600)

    def render(request: Request, name: str, status: int = 200, **ctx: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, ctx, status_code=status)

    def own_job(user: User, job_id: str) -> Job:
        if not JOB_ID_RE.fullmatch(job_id):
            raise HTTPException(404)
        job = db.get_job(job_id)
        if job is None or not hmac.compare_digest(job.email, user.email):
            raise HTTPException(404)
        return job

    # Kopya üretimi istek içinde çalışır (ayrı süreç, 2 GB'a kadar); sayaç yalnızca olay döngüsünde
    # değişir, kontrol ile artırma arasında await olmadığından yarış yoktur (ONERILER Ö6).
    outputs_running: dict[str, int] = {}

    def check_job_limits(email: str) -> None:
        if db.active_jobs(email) + outputs_running.get(email, 0) >= settings.max_active_jobs:
            raise HTTPException(429, "Aynı anda en fazla iki denetim yapılabilir.")
        if db.jobs_since(email, time.time() - 86400) >= settings.max_daily_jobs:
            raise HTTPException(429, "Günlük denetim sınırına ulaştınız. Yarın yeniden deneyin.")

    def check_queue() -> None:
        if runner.queued() >= settings.max_queued_jobs:
            raise HTTPException(503, SERVER_BUSY)

    def domain_allowed(email: str) -> bool:
        if not settings.allowed_domains:
            return settings.dev
        domain = email.rsplit("@", 1)[1].lower()
        return domain in settings.allowed_domains

    # --- Sayfalar ----------------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        user = current_user(request)
        if user is None:
            return render(request, "login.html", page=login_page, tiles=login_tiles)
        jobs = db.recent_jobs(user.email)
        return render(request, "upload.html", user=user, active="docs", rulesets=ordered_rulesets,
                      ruleset_groups=ruleset_groups,
                      jobs=jobs, max_mb=settings.max_upload_bytes // (1024 * 1024),
                      retention=int(settings.retention_hours))

    @app.get("/sablon/{ruleset_id}/latex.zip")
    def latex_template(ruleset_id: str) -> Response:
        info = rulesets.get(ruleset_id)
        if info is None:
            raise HTTPException(404)
        data = latex_zips.get(ruleset_id)
        if data is None:
            data = latex_zips[ruleset_id] = build_zip(info.rules)
        name = f"synora-{ruleset_id}-latex.zip"
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/fiyatlandirma", response_class=HTMLResponse)
    def pricing(request: Request) -> HTMLResponse:
        return render(request, "pricing.html", user=current_user(request), active="pricing")

    def auth_form(request: Request, mode: Literal["login", "register"], status: int = 200,
                  error: str | None = None, email: str = "") -> HTMLResponse:
        token = pre_csrf(request)
        resp = render(request, "auth.html", status=status, csrf=token, mode=mode,
                      domains=settings.allowed_domains, error=error, email=email)
        set_pre_csrf(resp, token)
        return resp

    async def send_link(request: Request, mode: Literal["login", "register"]) -> HTMLResponse:
        """Giriş ve kayıt ortak akışı: denetimler, tek kullanımlık bağlantı, e-posta."""
        form = await request.form()
        check_csrf(request.cookies.get(PRE_CSRF_COOKIE, ""), str(form.get("csrf", "")))
        email = str(form.get("email", "")).strip().lower()

        def fail(msg: str) -> HTMLResponse:
            return auth_form(request, mode, status=400, error=msg, email=email)

        if not EMAIL_RE.fullmatch(email):
            return fail("Geçerli bir e-posta adresi yazın.")
        if not domain_allowed(email):
            return fail(
                "Pilot süresince yalnızca üniversite e-posta adresleriyle giriş yapılabilir."
            )
        consent = None
        if mode == "register":
            if form.get("kvkk") != "1":
                return fail("Devam etmek için aydınlatma metnini onaylayın.")
            consent = TERMS_VERSION
        if db.login_requests_since(email, time.time() - 3600) >= settings.login_requests_per_hour:
            return fail("Çok fazla giriş isteği gönderildi. Bir saat sonra yeniden deneyin.")
        login_token = secrets.token_urlsafe(32)
        token_hash = _hash(login_token)
        db.add_login_token(token_hash, email, settings.login_token_minutes * 60, consent=consent)
        try:
            # smtplib eşzamanlı ve 20 sn bekleyebilir: olay döngüsünü kilitlemesin.
            await run_in_threadpool(mailer.send_login_link, email,
                                    f"{settings.base_url}/auth?token={login_token}")
        except (smtplib.SMTPException, OSError) as exc:
            db.delete_login_token(token_hash)  # gönderilemeyen bağlantı sınırdan düşmesin
            log_event("mail.failed", code=type(exc).__name__)
            return auth_form(request, mode, status=503, email=email,
                             error="E-posta gönderilemedi. Birkaç dakika sonra yeniden deneyin.")
        return render(request, "login_sent.html", email=email, mode=mode,
                      minutes=int(settings.login_token_minutes))

    @app.get("/giris", response_class=HTMLResponse)
    def login_page_view(request: Request) -> Response:
        if current_user(request) is not None:
            return RedirectResponse("/", status_code=303)
        return auth_form(request, "login")

    @app.get("/kayit", response_class=HTMLResponse)
    def register_page(request: Request) -> Response:
        if current_user(request) is not None:
            return RedirectResponse("/", status_code=303)
        return auth_form(request, "register")

    @app.get("/aydinlatma", response_class=HTMLResponse)
    def privacy_notice(request: Request) -> HTMLResponse:
        return render(request, "privacy.html", user=current_user(request),
                      retention=int(settings.retention_hours),
                      session_hours=int(settings.session_hours),
                      link_minutes=int(settings.login_token_minutes), version=TERMS_VERSION)

    @app.post("/login", response_class=HTMLResponse)
    async def login(request: Request) -> HTMLResponse:
        return await send_link(request, "login")

    @app.post("/kayit", response_class=HTMLResponse)
    async def register(request: Request) -> HTMLResponse:
        return await send_link(request, "register")

    @app.get("/auth", response_class=HTMLResponse)
    def auth_confirm(request: Request, token: str = "") -> HTMLResponse:
        # E-posta tarayıcıları bağlantıyı önceden açabilir: GET bağlantıyı tüketmez.
        valid = bool(token) and db.login_token_valid(_hash(token))
        csrf = pre_csrf(request)
        resp = render(request, "auth_confirm.html", status=200 if valid else 400,
                      token=token if valid else "", csrf=csrf, valid=valid)
        set_pre_csrf(resp, csrf)
        return resp

    @app.post("/auth")
    async def auth(request: Request) -> Response:
        form = await request.form()
        check_csrf(request.cookies.get(PRE_CSRF_COOKIE, ""), str(form.get("csrf", "")))
        email = db.consume_login_token(_hash(str(form.get("token", ""))))
        if email is None:
            return RedirectResponse("/auth", status_code=303)
        sid = secrets.token_urlsafe(32)
        db.add_session(_hash(sid), email, secrets.token_urlsafe(24),
                       settings.session_hours * 3600)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax",
                        secure=settings.secure_cookies, max_age=int(settings.session_hours * 3600))
        resp.delete_cookie(PRE_CSRF_COOKIE)
        return resp

    @app.post("/logout")
    async def logout(request: Request) -> Response:
        user = require_user(request)
        form = await request.form()
        check_csrf(user.csrf, str(form.get("csrf", "")))
        db.delete_session(user.session_hash)
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    # --- İşler -------------------------------------------------------------------------------

    @app.post("/jobs")
    async def create_job(request: Request) -> JSONResponse:
        user = require_user(request)
        check_csrf(user.csrf, request.headers.get("x-csrf-token"))
        ruleset = rulesets.get(request.headers.get("x-ruleset", ""))
        if ruleset is None:
            raise HTTPException(400, "Kural seti bulunamadı.")
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes:
            raise HTTPException(413, "Dosya çok büyük.")
        check_job_limits(user.email)

        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():  # bellekte, sınırla; diske yazılmaz
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise HTTPException(413, "Dosya çok büyük.")
            chunks.append(chunk)
        if size == 0:
            raise HTTPException(400, "Dosya boş.")
        # Gövde okunurken paralel istekler aynı kontrolü geçmiş olabilir; buradan sonra await
        # yok, yeniden kontrol ile kayıt arasına başka istek giremez.
        check_job_limits(user.email)
        check_queue()
        job_id = secrets.token_urlsafe(18)
        db.add_job(job_id, user.email, ruleset.id)
        runner.submit(job_id, b"".join(chunks), str(ruleset.path))
        return JSONResponse({"id": job_id, "url": f"/jobs/{job_id}"}, status_code=202)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: str) -> Response:
        user = current_user(request)
        if user is None:
            return RedirectResponse("/", status_code=303)
        job = own_job(user, job_id)
        report = json.loads(job.report) if job.report else None
        view = report_view(report) if report else None
        if report and view:
            view["pending"] = pending_roles(job, report)
            view["roles_changed"] = view["pending"] != applied_roles(report)
        return render(request, "job.html", user=user, job=job, view=view,
                      error=job_error_message(job.error_code) if job.status == "failed" else None,
                      ruleset=rulesets.get(job.ruleset), retention=int(settings.retention_hours))

    @app.get("/jobs/{job_id}/status")
    def job_status(request: Request, job_id: str) -> JSONResponse:
        job = own_job(require_user(request), job_id)
        return JSONResponse({"status": job.status})

    @app.get("/jobs/{job_id}/report.json")
    def job_report(request: Request, job_id: str) -> Response:
        job = own_job(require_user(request), job_id)
        if not job.report:
            raise HTTPException(404)
        return Response(job.report, media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="synora-rapor.json"'})

    @app.post("/jobs/{job_id}/delete")
    async def job_delete(request: Request, job_id: str) -> Response:
        user = require_user(request)
        form = await request.form()
        check_csrf(user.csrf, str(form.get("csrf", "")))
        own_job(user, job_id)
        db.delete_job(job_id)
        return RedirectResponse("/", status_code=303)

    async def same_file(request: Request, expected_sha256: str) -> bytes:
        """Sunucu tezi saklamadığından öğrenci aynı dosyayı yeniden gönderir; bellekte okunur,
        yalnızca SHA-256 özeti karşılaştırılır."""
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise HTTPException(413, "Dosya çok büyük.")
            chunks.append(chunk)
        data = b"".join(chunks)
        if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected_sha256):
            raise HTTPException(409, "Bu, denetlenen dosya değil. Aynı dosyayı seçin ya da "
                                     "yeni dosya için yeni bir denetim başlatın.")
        return data

    @app.post("/jobs/{job_id}/roles")
    async def job_roles(request: Request, job_id: str) -> JSONResponse:
        """Rolü belirsiz paragraflar için öğrencinin seçimi. Yalnızca paragraf kimliği ve izinli
        bir rol adı alınır; metin alınmaz. Boş rol seçimi kaldırır."""
        user = require_user(request)
        check_csrf(user.csrf, request.headers.get("x-csrf-token"))
        job = own_job(user, job_id)
        if job.status != "done" or not job.report:
            raise HTTPException(409, "Bu denetim için rol seçilemiyor.")
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "Geçersiz istek.") from None
        changes = body.get("roles") if isinstance(body, dict) else None
        if not isinstance(changes, dict) or len(changes) > MAX_USER_ROLES:
            raise HTTPException(400, "Geçersiz istek.")
        report = json.loads(job.report)
        editable = {b["pid"] for b in report.get("document") or [] if "pid" in b}
        pending = pending_roles(job, report)
        for pid, role in changes.items():
            if pid not in editable or not isinstance(role, str) or (
                role and role not in ROLE_CHOICES
            ):
                raise HTTPException(400, "Geçersiz paragraf ya da rol.")
            if role:
                pending[pid] = role
            else:
                pending.pop(pid, None)
        db.set_user_roles(job_id, json.dumps(pending, sort_keys=True))
        return JSONResponse({"roles": pending, "changed": pending != applied_roles(report)})

    @app.post("/jobs/{job_id}/recheck")
    async def job_recheck(request: Request, job_id: str) -> JSONResponse:
        """Seçilen rollerle aynı dosyayı yeniden denetler."""
        user = require_user(request)
        check_csrf(user.csrf, request.headers.get("x-csrf-token"))
        job = own_job(user, job_id)
        ruleset = rulesets.get(job.ruleset)
        if job.status != "done" or ruleset is None or not job.source_sha256 or not job.report:
            raise HTTPException(409, "Bu denetim yeniden çalıştırılamıyor.")
        check_job_limits(user.email)
        data = await same_file(request, job.source_sha256)
        job = own_job(user, job_id)  # beklerken başka bir istek yeniden kuyruğa almış olabilir
        if job.status != "done" or not job.report:
            raise HTTPException(409, "Bu denetim zaten yeniden denetleniyor.")
        check_job_limits(user.email)
        check_queue()
        roles = pending_roles(job, json.loads(job.report))
        db.requeue(job_id)
        runner.submit(job_id, data, str(ruleset.path), roles)
        del data
        return JSONResponse({"id": job_id, "url": f"/jobs/{job_id}"}, status_code=202)

    @app.post("/jobs/{job_id}/output/{kind}")
    async def job_output(request: Request, job_id: str, kind: str) -> Response:
        """Düzeltilmiş ya da yorumlu kopya. Sunucu tezi saklamadığı için öğrenci aynı dosyayı
        yeniden seçer; yalnızca SHA-256 özeti karşılaştırılır, sonuç doğrudan indirilir."""
        user = require_user(request)
        check_csrf(user.csrf, request.headers.get("x-csrf-token"))
        if kind not in OUTPUT_FILES:
            raise HTTPException(404)
        job = own_job(user, job_id)
        ruleset = rulesets.get(job.ruleset)
        if job.status != "done" or ruleset is None or not job.source_sha256 or not job.report:
            raise HTTPException(409, "Bu denetim için kopya üretilemiyor.")
        check_job_limits(user.email)
        if sum(outputs_running.values()) >= settings.workers:
            raise HTTPException(503, SERVER_BUSY)
        outputs_running[user.email] = outputs_running.get(user.email, 0) + 1
        try:
            data = await same_file(request, job.source_sha256)
            # Kopya, ekrandaki raporla aynı rollerle üretilir (kaydedilmiş ama henüz yeniden
            # denetlenmemiş seçimlerle değil).
            roles = applied_roles(json.loads(job.report))
            result = await run_in_threadpool(runner.make_output, kind,  # type: ignore[arg-type]
                                             job_id, data, str(ruleset.path), roles)
            del data
        finally:
            left = outputs_running[user.email] - 1
            if left:
                outputs_running[user.email] = left
            else:
                del outputs_running[user.email]
        if result["docx"] is None:
            code = result["error_code"] or "INTERNAL"
            message = OUTPUT_ERRORS.get(code, "Belge otomatik olarak işlenemedi; metninizin "
                                              "korunması için dosya üretilmedi. Raporu kullanarak "
                                              "Word'de düzeltebilirsiniz.")
            raise HTTPException(422, f"{message} (kod: {code})")
        return Response(result["docx"], media_type=DOCX_TYPE, headers={
            "Content-Disposition": f'attachment; filename="{OUTPUT_FILES[kind]}"'})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> Response:
        if request.method == "POST" and (
            request.url.path == "/jobs" or "/output/" in request.url.path
            or request.url.path.endswith(("/roles", "/recheck"))
        ):
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        if exc.status_code == 401:
            return RedirectResponse("/", status_code=303)
        messages = {403: "Oturum doğrulaması başarısız. Sayfayı yenileyip yeniden deneyin.",
                    404: "Aradığınız sayfa bulunamadı ya da süresi doldu."}
        return render(request, "error.html", status=exc.status_code,
                      message=messages.get(exc.status_code, str(exc.detail)))

    return app
