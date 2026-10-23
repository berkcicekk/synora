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
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from synora.check import USER_ROLES
from synora.errors import ErrorCode
from synora.latex import build_zip
from synora.log import log_event
from synora.report import ROLE_NAMES, SEVERITY_NAMES, ingest_message, rule_label
from synora.ruleset import Ruleset, load_ruleset
from synora.web.db import Database, Job
from synora.web.mailer import Mailer, make_mailer
from synora.web.pipeline import run_pipeline
from synora.web.presentation import PageSpec, RuleTile, page_spec, rule_tiles
from synora.web.settings import Settings
from synora.web.worker import JobRunner
from synora.word import build_docx

HERE = Path(__file__).resolve().parent
SESSION_COOKIE = "synora_session"
PRE_CSRF_COOKIE = "synora_pre"
# Kayıtta onaylanan aydınlatma metninin sürümü; metin değişince artırılır.
TERMS_VERSION = "aydinlatma-taslak-2026-10"
SERVER_BUSY = "Sunucu şu an yoğun. Bir dakika sonra yeniden deneyin."
MAX_FORM_BYTES = 8 * 1024
MAX_JSON_BYTES = 64 * 1024
JSON_ERRORS = {
    401: "Oturumunuz sona erdi. Sayfayı yenileyip yeniden giriş yapın.",
    403: "Oturum doğrulaması başarısız. Sayfayı yenileyip yeniden deneyin.",
    404: "Denetim bulunamadı ya da süresi doldu.",
}
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
        except (ValidationError, OSError, ValueError, yaml.YAMLError):
            continue  # bozuk bir kılavuz dosyası diğerlerini ve açılışı etkilemesin
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
            "checked": report.get("checked_rules") or [],  # eski raporlarda alan yok
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
    # Sayılar şeridi: kural seti / üniversite sayısı keşiften; doğruluk oranı 37 resmi şablonda
    # 1840 denemelik bozma ölçümünden (.gece/CAPRAZ_DOGRULAMA.md, 2026-10-20: yakalama %97,1).
    landing_stats = {
        "formats": len(rulesets),
        "universities": len({r.rules.institution for r in rulesets.values()
                             if r.rules.institution}),
        "accuracy": "%97,1",
    }
    # LaTeX şablonu ilk istendiğinde kural setinden üretilip saklanır (kullanıcı girdisi yok;
    # yalnızca keşfedilmiş kural seti kimlikleri kabul edilir).
    latex_zips: dict[str, bytes] = {}
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["when"] = format_when
    templates.env.filters["date_tr"] = format_date
    templates.env.globals["now"] = time.time
    # Saklama sözü her sayfada ayardan gelir (sabit "24 saat" ayar değişince yanlış söz olurdu).
    templates.env.globals["retention_hours"] = int(settings.retention_hours)
    # Statik dosyalar için sürüm damgası: içerik değişince tarayıcı önbelleği geçersizleşir.
    asset_hash = hashlib.sha256()
    for name in ("app.css", "app.js", "fonts.css", "landing.js", "docview.js"):
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
        try:
            response = await call_next(request)
        except Exception as exc:
            # Burada yakalanır ki ServerErrorMiddleware yeniden fırlatıp ayrıntılı iz kaydı
            # (olası tez içeriğiyle) yazmasın; sayfa da güvenlik başlıklarını alsın.
            response = server_error_page(request, exc)
        h = response.headers
        h["Content-Security-Policy"] = CSP
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "no-referrer"
        h["X-Frame-Options"] = "DENY"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        if not request.url.path.startswith("/static"):
            h["Cache-Control"] = "no-store"
        elif request.query_params.get("v") and response.status_code == 200:
            # Sürüm damgalı adres içerik değişince değişir: tarayıcı bir yıl saklayabilir.
            h["Cache-Control"] = "public, max-age=31536000, immutable"
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
        if job is None or not hmac.compare_digest(job.email, user.email) or expired(job):
            raise HTTPException(404)
        return job

    def expired(job: Job) -> bool:
        # Temizlik görevi 10 dakikada bir çalışır; "24 saat sonra silinir" sözü okurken de tutulur.
        return job.created_at < time.time() - settings.retention_hours * 3600

    # Kopya üretimi istek içinde çalışır (ayrı süreç, 2 GB'a kadar); sayaç yalnızca olay döngüsünde
    # değişir, kontrol ile artırma arasında await olmadığından yarış yoktur (ONERILER Ö6).
    outputs_running: dict[str, int] = {}

    def check_active(email: str) -> None:
        if db.active_jobs(email) + outputs_running.get(email, 0) >= settings.max_active_jobs:
            raise HTTPException(429, "Aynı anda en fazla iki denetim yapılabilir.")

    def check_job_limits(email: str) -> None:
        """Yeni yükleme: eşzamanlı ve günlük sınır (kopya ve yeniden denetim günlük sayılmaz)."""
        check_active(email)
        if db.jobs_since(email, time.time() - 86400) >= settings.max_daily_jobs:
            raise HTTPException(429, "Günlük denetim sınırına ulaştınız. Yarın yeniden deneyin.")

    async def small_body(request: Request, content_type: str, limit: int) -> bytes:
        """Küçük, beklenen türde gövde; büyüğü okumadan reddedilir."""
        if request.headers.get("content-type", "").split(";")[0].strip() != content_type:
            raise HTTPException(415, "Desteklenmeyen istek biçimi.")
        length = request.headers.get("content-length", "")
        if not length.isdigit() or int(length) > limit:
            raise HTTPException(413, "İstek çok büyük.")
        body = await request.body()
        if len(body) > limit:
            raise HTTPException(413, "İstek çok büyük.")
        return body

    async def small_form(request: Request) -> FormData:
        # Yalnızca URL kodlu küçük formlar: Starlette çok parçalı gövdeyi 1 MB'tan sonra diske
        # yazar; oturumsuz /login ile disk doldurulabilirdi. Gövdesiz istek boş formdur (CSRF
        # denetimi reddeder).
        if request.headers.get("content-length", "0") == "0" and \
                "transfer-encoding" not in request.headers:
            return FormData()
        body = await small_body(request, "application/x-www-form-urlencoded", MAX_FORM_BYTES)
        pairs: list[tuple[str, str | UploadFile]] = [
            (k, v) for k, v in parse_qsl(body.decode("latin-1"), keep_blank_values=True)]
        return FormData(pairs)

    def check_queue() -> None:
        if runner.queued() >= settings.max_queued_jobs:
            raise HTTPException(503, SERVER_BUSY)

    def domain_allowed(email: str) -> bool:
        if not settings.allowed_domains:
            return settings.dev
        domain = email.rsplit("@", 1)[1].lower()
        # Nokta ile başlayan girdi sonek kuralı: ".edu.tr" → *.edu.tr biten her alan adı.
        return any(domain == d or (d.startswith(".") and domain.endswith(d))
                   for d in settings.allowed_domains)

    # --- Sayfalar ----------------------------------------------------------------------------

    def _ruleset_name(ruleset_id: str) -> str:
        info = rulesets.get(ruleset_id)
        return info.name if info else ruleset_id

    def _hours_left(job: Job) -> int:
        left = settings.retention_hours - (time.time() - job.created_at) / 3600
        return max(0, round(left))

    def panel_context(user: User) -> dict[str, Any]:
        """Panel kartları ve son denetimler tablosu; rapor metni içermez (yalnızca sayılar)."""
        jobs = [j for j in db.recent_jobs(user.email) if not expired(j)]
        rows: list[dict[str, Any]] = []
        latest: dict[str, Any] | None = None
        frequent: list[tuple[str, int]] = []
        for j in jobs:
            findings_n = None
            if j.status == "done" and j.report:
                report = json.loads(j.report)
                findings_n = len(report.get("findings") or [])
                if latest is None:
                    s = report.get("summary") or {}
                    latest = {"id": j.id, "when": format_when(j.created_at),
                              "errors": s.get("errors", 0), "warnings": s.get("warnings", 0),
                              "fixable": s.get("fixable", 0), "findings": findings_n,
                              "ruleset_name": _ruleset_name(j.ruleset),
                              "ruleset": j.ruleset, "hours_left": _hours_left(j)}
                    counts: dict[str, int] = {}
                    for f in report.get("findings") or []:
                        counts[f["rule_id"]] = counts.get(f["rule_id"], 0) + 1
                    frequent = [(rule_label(rid), n) for rid, n in
                                sorted(counts.items(), key=lambda kv: -kv[1])[:3]]
            rows.append({"id": j.id, "when": format_when(j.created_at), "status": j.status,
                         "ruleset_name": _ruleset_name(j.ruleset), "findings": findings_n,
                         "hours_left": _hours_left(j)})
        shown = (rulesets.get((latest or {}).get("ruleset", ""))
                 or rulesets.get(settings.default_ruleset)
                 or (ordered_rulesets[0] if ordered_rulesets else None))
        # Kâğıt ve yazı tipi kendini anlatır; ölçüler etiketsiz anlamsız ("3 cm" neyin?).
        chips = [t.value if t.label in ("Kağıt", "Yazı tipi") else f"{t.label} {t.value}"
                 for t in rule_tiles(shown.rules)[:7]] if shown else []
        # Panelden sürükle-bırak yükleme varsayılan kılavuzla yapılır; kart adını gösterir.
        default = ordered_rulesets[0] if ordered_rulesets else None
        return {"rows": rows, "latest": latest, "frequent": frequent, "chips": chips,
                "ruleset_name": shown.name if shown else "—",
                "template_href": f"/sablon/{shown.id}/sablon.docx" if shown else "/",
                "upload_ruleset": default.id if default else "",
                "upload_ruleset_name": default.name if default else "",
                "max_bytes": settings.max_upload_bytes}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        user = current_user(request)
        if user is None:
            return render(request, "login.html", page=login_page, tiles=login_tiles,
                          stats={**landing_stats, "users": db.user_count()})
        return render(request, "panel.html", user=user, active="panel",
                      panel=panel_context(user), retention=int(settings.retention_hours))

    @app.get("/yukle", response_class=HTMLResponse)
    def upload_page(request: Request) -> Response:
        user = current_user(request)
        if user is None:
            return RedirectResponse("/giris", status_code=303)
        latest_done = next((j.id for j in db.recent_jobs(user.email)
                            if j.status == "done" and not expired(j)), None)
        return render(request, "upload.html", user=user, active="yukle",
                      rulesets=ordered_rulesets, ruleset_groups=ruleset_groups,
                      latest_done=latest_done,
                      max_mb=settings.max_upload_bytes // (1024 * 1024),
                      retention=int(settings.retention_hours))

    word_templates: dict[str, bytes] = {}

    @app.get("/sablon/{ruleset_id}/sablon.docx")
    def word_template(ruleset_id: str) -> Response:
        """Kural setinden stilleri hazır Word şablonu; ilk istekte üretilip saklanır."""
        info = rulesets.get(ruleset_id)
        if info is None:
            raise HTTPException(404)
        data = word_templates.get(ruleset_id)
        if data is None:
            data = word_templates[ruleset_id] = build_docx(info.rules)
        name = f"payper-{ruleset_id}-sablon.docx"
        return Response(
            data,
            media_type="application/vnd.openxmlformats-officedocument"
                       ".wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{name}"'})

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
                      domains=settings.allowed_domains, error=error, email=email,
                      direct=not settings.email_verification)
        set_pre_csrf(resp, token)
        return resp

    # Ö7: istemci başına istek sınırı. Bellek içi ve hash'li: ham IP hiçbir yerde
    # tutulmaz, pencere dolunca kayıt düşer. Uygulamaya yalnızca 127.0.0.1 (tünel/vekil)
    # üzerinden ulaşılabildiği için CF-Connecting-IP başlığı güvenilirdir; yoksa soket adresi.
    def _client_key(request: Request) -> str:
        ip = (request.headers.get("cf-connecting-ip")
              or (request.client.host if request.client else "?"))
        return hashlib.sha256(ip.encode()).hexdigest()[:16]

    def make_rate_limiter(per_ip_hour: int, per_minute: int) -> Callable[[Request], bool]:
        all_hits: dict[str, list[float]] = {}
        all_recent: list[float] = []

        def rate_ok(request: Request) -> bool:
            now = time.time()
            key = _client_key(request)
            hits = [t for t in all_hits.get(key, []) if t > now - 3600]
            recent = [t for t in all_recent if t > now - 60]
            all_recent[:] = recent
            if len(hits) >= per_ip_hour or len(recent) >= per_minute:
                all_hits[key] = hits
                return False
            hits.append(now)
            all_hits[key] = hits
            all_recent.append(now)
            if len(all_hits) > 1000:  # sözlük sınırsız büyümesin
                for stale in [k for k, v in all_hits.items() if not v or v[-1] <= now - 3600]:
                    del all_hits[stale]
            return True

        return rate_ok

    login_rate_ok = make_rate_limiter(settings.login_requests_per_ip_hour,
                                      settings.login_requests_per_minute)
    suggestion_rate_ok = make_rate_limiter(settings.suggestions_per_ip_hour,
                                           settings.suggestions_per_minute)

    def open_session(email: str) -> RedirectResponse:
        sid = secrets.token_urlsafe(32)
        db.add_session(_hash(sid), email, secrets.token_urlsafe(24),
                       settings.session_hours * 3600)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax",
                        secure=settings.secure_cookies, max_age=int(settings.session_hours * 3600))
        resp.delete_cookie(PRE_CSRF_COOKIE)
        return resp

    async def send_link(request: Request, mode: Literal["login", "register"]) -> Response:
        """Giriş ve kayıt ortak akışı: denetimler, tek kullanımlık bağlantı, e-posta.

        email_verification kapalıyken (demo kipi) bağlantı yerine oturum hemen açılır."""
        form = await small_form(request)
        email = str(form.get("email", "")).strip().lower()
        expected, provided = request.cookies.get(PRE_CSRF_COOKIE, ""), str(form.get("csrf", ""))
        if not provided or not hmac.compare_digest(expected, provided):
            # Form uzun süre açık kalmış: yazılan adres kaybolmasın, yeni formla gönderilsin.
            return auth_form(request, mode, status=403, email=email, error=(
                "Sayfanın süresi doldu. Adresinizi kontrol edip yeniden gönderin."))

        def fail(msg: str) -> HTMLResponse:
            return auth_form(request, mode, status=400, error=msg, email=email)

        if not login_rate_ok(request):
            return auth_form(request, mode, status=429, email=email, error=(
                "Çok fazla deneme yapıldı. Bir süre sonra yeniden deneyin."))
        if not EMAIL_RE.fullmatch(email):
            return fail("Geçerli bir e-posta adresi yazın.")
        if not domain_allowed(email):
            return fail(
                "Pilot süresince yalnızca üniversite e-posta adresleri kullanılabilir."
            )
        consent = None
        if mode == "register":
            if form.get("kvkk") != "1":
                return fail("Devam etmek için aydınlatma metnini onaylayın.")
            consent = TERMS_VERSION
        if db.login_requests_since(email, time.time() - 3600) >= settings.login_requests_per_hour:
            return fail("Çok fazla giriş isteği gönderildi. Bir saat sonra yeniden deneyin.")
        if not settings.email_verification:
            # Demo kipi: adres sahipliği doğrulanmadan oturum açılır (bkz. Settings).
            # ttl=0 bağlantısı kullanılamaz; yalnızca saatlik istek sayacına yazılır.
            db.add_login_token(_hash(secrets.token_urlsafe(32)), email, 0)
            if mode == "register":
                db.register_user(email, TERMS_VERSION)
            elif db.user_consent(email) is None:
                return fail("Bu adres kayıtlı değil. Önce kayıt olun.")
            return open_session(email)
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

    demo_state: dict[str, Any] = {}

    @app.get("/robots.txt", response_class=Response)
    def robots() -> Response:
        # Meşruiyet sinyali (güvenlik filtreleri ve tarayıcılar için): gezinmeye açık,
        # kullanıcıya özel sayfalar zaten girişsiz erişilemez.
        return Response("User-agent: *\nAllow: /\nDisallow: /jobs/\n",
                        media_type="text/plain; charset=utf-8")

    @app.get("/.well-known/security.txt", response_class=Response)
    def security_txt() -> Response:
        """RFC 9116: güvenlik bildirimleri için iletişim. Kişisel e-posta yayımlanmaz;
        iletişim herkese açık GitHub deposu üzerinden."""
        body = (
            "Contact: https://github.com/berkcicekk/synora/issues\n"
            f"Canonical: {settings.base_url}/.well-known/security.txt\n"
            "Preferred-Languages: tr, en\n"
            "Expires: 2027-10-01T00:00:00.000Z\n"
        )
        return Response(body, media_type="text/plain; charset=utf-8")

    @app.get("/llms.txt", response_class=Response)
    def llms_txt() -> Response:
        """llmstxt.org: yapay zekâ asistanlarına site tanıtımı. Tez metni içermez;
        yalnızca herkese açık sayfalar ve gizlilik ilkeleri anlatılır."""
        body = (
            "# Payper\n\n"
            "> Payper, .docx tezleri üniversitenin resmi yazım kılavuzuna göre denetleyen "
            "ve biçim hatalarını düzelten ücretsiz bir web aracıdır. "
            f"{len(rulesets)} üniversite kural seti hazır yüklüdür.\n\n"
            "Önemli: Payper tezin metnini ASLA değiştirmez ve hiçbir yapay zekâ modeli tez "
            "metnini görmez; yalnızca biçim (kenar boşluğu, yazı tipi, satır aralığı, başlık "
            "stilleri, sayfa numarası) denetlenir ve düzeltilir. Yüklenen dosya diske "
            "yazılmaz; rapor 24 saat içinde silinir.\n\n"
            "## Sayfalar\n\n"
            f"- [Ana sayfa]({settings.base_url}/): yükle → rapor → düzeltilmiş kopyayı indir\n"
            f"- [Örnek rapor]({settings.base_url}/demo): kayıt olmadan canlı örnek denetim\n"
            f"- [Kayıt]({settings.base_url}/kayit): üniversite e-postasıyla, ücretsiz\n"
            f"- [Fiyatlandırma]({settings.base_url}/fiyatlandirma)\n"
            f"- [KVKK aydınlatma metni]({settings.base_url}/aydinlatma)\n\n"
            "## Kaynaklar\n\n"
            "- [GitHub](https://github.com/berkcicekk/synora): kaynak kod ve kural setleri\n"
            f"- [security.txt]({settings.base_url}/.well-known/security.txt)\n\n"
            "## English summary\n\n"
            "Payper checks Turkish university theses (.docx) against the institution's "
            "official formatting guide and fixes formatting errors without ever modifying "
            "the thesis text. No AI model sees the text; uploads are processed in memory "
            "and never written to disk. Free during the pilot; sign in with a university "
            "e-mail address.\n"
        )
        return Response(body, media_type="text/markdown; charset=utf-8")

    @app.post("/oneri")
    async def suggest(request: Request) -> JSONResponse:
        """İstek/öneri kutusu (her sayfadaki popup). Girişsiz de gönderilebilir.

        CSRF: yalnızca fetch kabul edilir — siteler arası klasik form özel başlık
        koyamaz; koyarsa CORS ön denetimi keser. Girişliyse oturum CSRF'si de aranır.
        """
        if request.headers.get("x-requested-with") != "fetch":
            raise HTTPException(403, "CSRF")
        user = current_user(request)
        if user is not None:
            check_csrf(user.csrf, request.headers.get("x-csrf-token"))
        form = await small_form(request)
        if str(form.get("website", "")):  # bal küpü: insan görmez, bot doldurur
            return JSONResponse({"ok": True})
        message = " ".join(str(form.get("message", "")).split())
        if not message or len(message) > 2000:
            raise HTTPException(400, "Mesaj boş olamaz (en çok 2000 karakter).")
        email = user.email if user else str(form.get("email", "")).strip()
        if email and user is None and not EMAIL_RE.fullmatch(email):
            raise HTTPException(400, "E-posta adresi geçersiz görünüyor.")
        page = str(form.get("page", ""))[:200]
        if not page.startswith("/"):
            page = ""
        if not suggestion_rate_ok(request):
            raise HTTPException(429, "Çok sık gönderildi. Birkaç dakika sonra yeniden deneyin.")
        db.add_suggestion(message, email, page)
        log_event("suggestion.added", count=len(message))
        return JSONResponse({"ok": True})

    @app.get("/demo", response_class=HTMLResponse)
    def demo_page(request: Request) -> HTMLResponse:
        """Girişsiz örnek rapor: pakete gömülü sentetik tez, varsayılan kural setiyle.

        Kullanıcı girdisi yok; sonuç deterministik olduğundan ilk istekte üretilip
        bellekte tutulur. Rol düzenleme ve kopya üretimi kapalıdır.
        """
        if "report" not in demo_state:
            sample = (HERE / "static" / "ornek-tez.docx").read_bytes()
            default = rulesets[settings.default_ruleset]
            outcome = run_pipeline(sample, str(default.path), job_id="demo")
            if outcome["report"] is None:  # pragma: no cover - sentetik belge hep geçer
                raise HTTPException(503, SERVER_BUSY)
            demo_state["report"] = json.loads(outcome["report"])
        view = report_view(demo_state["report"])
        view["pending"] = {}
        view["roles_changed"] = False
        view["editable"] = 0
        for b in view["blocks"]:
            b.pop("pid", None)  # rol düzenleme demo'da kapalı
        job = Job(id="demo", email="", ruleset=settings.default_ruleset, status="done",
                  created_at=time.time(), finished_at=None, error_code=None, report=None)
        return render(request, "job.html", user=current_user(request), job=job, view=view,
                      demo=True, error=None, ruleset=rulesets.get(settings.default_ruleset),
                      retention=int(settings.retention_hours))

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
    async def login(request: Request) -> Response:
        return await send_link(request, "login")

    @app.post("/kayit", response_class=HTMLResponse)
    async def register(request: Request) -> Response:
        return await send_link(request, "register")

    @app.get("/auth", response_class=HTMLResponse)
    def auth_confirm(request: Request, token: str = "") -> HTMLResponse:
        # E-posta tarayıcıları bağlantıyı önceden açabilir: GET bağlantıyı tüketmez.
        valid = bool(token) and db.login_token_valid(_hash(token))
        return confirm_page(request, token if valid else "", valid=valid)

    def confirm_page(request: Request, token: str, valid: bool, error: str | None = None,
                     status: int | None = None) -> HTMLResponse:
        csrf = pre_csrf(request)
        # Kayıt bağlantısı: formu başkası doldurmuş olabilir; onay kutusunu adres sahibi işaretler.
        needs_consent = valid and db.login_token_consent(_hash(token)) is not None
        resp = render(request, "auth_confirm.html", status=status or (200 if valid else 400),
                      token=token, csrf=csrf, valid=valid, needs_consent=needs_consent,
                      error=error)
        set_pre_csrf(resp, csrf)
        return resp

    @app.post("/auth")
    async def auth(request: Request) -> Response:
        form = await small_form(request)
        check_csrf(request.cookies.get(PRE_CSRF_COOKIE, ""), str(form.get("csrf", "")))
        token = str(form.get("token", ""))
        if db.login_token_valid(_hash(token)) and db.login_token_consent(_hash(token)) and \
                form.get("kvkk") != "1":
            return confirm_page(request, token, valid=True, status=400,
                                error="Devam etmek için aydınlatma metnini onaylayın.")
        email = db.consume_login_token(_hash(token), consent_confirmed=form.get("kvkk") == "1")
        if email is None:
            return RedirectResponse("/auth", status_code=303)
        return open_session(email)

    @app.post("/logout")
    async def logout(request: Request) -> Response:
        user = require_user(request)
        form = await small_form(request)
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
        form = await small_form(request)
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
            body = json.loads(await small_body(request, "application/json", MAX_JSON_BYTES))
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
        if isinstance(body.get("collect"), bool):
            # F6 açık rızası: işaretliyse uygulanan seçimler, metinsiz özellik vektörü +
            # rol olarak eğitim verisine yazılır (yazma anı: worker, yeniden denetimde).
            db.set_collect(job_id, body["collect"])
        return JSONResponse({"roles": pending, "changed": pending != applied_roles(report)})

    @app.post("/jobs/{job_id}/feedback")
    async def job_feedback(request: Request, job_id: str) -> JSONResponse:
        """Ö1: "Bu bulgu yanlış mı?" oyu. Metin alınmaz; yalnızca rule_id ve karar."""
        user = require_user(request)
        check_csrf(user.csrf, request.headers.get("x-csrf-token"))
        job = own_job(user, job_id)
        form = await small_form(request)
        rule_id = str(form.get("rule_id", ""))
        verdict = str(form.get("verdict", ""))
        para_id = str(form.get("para_id", ""))[:64]
        if verdict not in ("wrong", "ok") or not re.fullmatch(r"[a-z0-9_.]{1,64}", rule_id):
            raise HTTPException(400, "Geçersiz geri bildirim.")
        if db.feedback_count(job_id) >= 200:  # sınırsız birikme olmasın
            raise HTTPException(429, "Bu iş için geri bildirim sınırına ulaşıldı.")
        info = rulesets.get(job.ruleset)
        version = info.rules.version if info else 0
        db.add_feedback(job_id, job.ruleset, version, rule_id, para_id, verdict)
        log_event("feedback", job_id=job_id, code=f"{rule_id}:{verdict}")
        return JSONResponse({"ok": True})

    @app.post("/jobs/{job_id}/recheck")
    async def job_recheck(request: Request, job_id: str) -> JSONResponse:
        """Seçilen rollerle aynı dosyayı yeniden denetler."""
        user = require_user(request)
        check_csrf(user.csrf, request.headers.get("x-csrf-token"))
        job = own_job(user, job_id)
        ruleset = rulesets.get(job.ruleset)
        if job.status != "done" or ruleset is None or not job.source_sha256 or not job.report:
            raise HTTPException(409, "Bu denetim yeniden çalıştırılamıyor.")
        check_active(user.email)
        data = await same_file(request, job.source_sha256)
        job = own_job(user, job_id)  # beklerken başka bir istek yeniden kuyruğa almış olabilir
        if job.status != "done" or not job.report:
            raise HTTPException(409, "Bu denetim zaten yeniden denetleniyor.")
        check_active(user.email)
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
        check_active(user.email)
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
    def health() -> JSONResponse:
        """İzleme için: veritabanı yanıt veriyor ve iş yürütücü iş parçacıkları çalışıyor mu."""
        try:
            db.execute("SELECT 1")
            healthy = runner.alive()
        except (sqlite3.Error, OSError):
            healthy = False
        return JSONResponse({"status": "ok" if healthy else "degraded"},
                            status_code=200 if healthy else 503)

    def api_request(request: Request) -> bool:
        """Arayüzün fetch ile çağırdığı uçlar JSON hata alır; diğerleri hata sayfası."""
        path = request.url.path
        return request.method == "POST" and (
            path == "/jobs" or "/output/" in path or path.endswith(("/roles", "/recheck")))

    # Yönlendiricinin fırlattığı starlette HTTPException (bilinmeyen adres, yanlış yöntem) dahil.
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        code = exc.status_code
        generic = exc.detail == HTTPStatus(code).phrase  # "Not Found" gibi İngilizce öntanımlı
        if api_request(request):
            message = (JSON_ERRORS.get(code, "İstek tamamlanamadı. Yeniden deneyin.")
                       if generic or code in (401, 403) else exc.detail)
            return JSONResponse({"error": message}, status_code=code, headers=exc.headers)
        if code == 401:
            return RedirectResponse("/", status_code=303)
        messages = {403: "Oturum doğrulaması başarısız. Sayfayı yenileyip yeniden deneyin.",
                    404: "Aradığınız sayfa bulunamadı ya da süresi doldu.",
                    405: "Bu adres bu şekilde açılamaz."}
        resp = render(request, "error.html", status=code, user=current_user(request),
                      message=messages.get(code, str(exc.detail)))
        resp.headers.update(exc.headers or {})  # ör. 405 için Allow
        return resp

    def server_error_page(request: Request, exc: Exception) -> Response:
        # Ayrıntı (ve olası tez içeriği) kullanıcıya ya da kayda gitmez; yalnızca hata türü.
        log_event("http.error", code=type(exc).__name__)
        message = "Beklenmeyen bir hata oluştu. Birkaç saniye sonra yeniden deneyin."
        if api_request(request):
            return JSONResponse({"error": message}, status_code=500)
        return render(request, "error.html", status=500, message=message)

    return app
