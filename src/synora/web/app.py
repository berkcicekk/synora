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
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from synora.errors import ErrorCode
from synora.report import ROLE_NAMES, SEVERITY_NAMES, ingest_message
from synora.ruleset import Ruleset, load_ruleset
from synora.web.db import Database, Job
from synora.web.mailer import Mailer, make_mailer
from synora.web.presentation import PageSpec, page_spec
from synora.web.settings import Settings
from synora.web.worker import JobRunner

HERE = Path(__file__).resolve().parent
SESSION_COOKIE = "synora_session"
PRE_CSRF_COOKIE = "synora_pre"
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


def job_error_message(code: str | None) -> str:
    if code in JOB_ERRORS:
        return JOB_ERRORS[code]
    try:
        return ingest_message(ErrorCode(code or ""))
    except ValueError:
        return JOB_ERRORS["INTERNAL"]


TR_TZ = timezone(timedelta(hours=3))  # Türkiye 2016'dan beri yaz saati uygulamıyor
TR_MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def format_when(ts: float) -> str:
    d = datetime.fromtimestamp(ts, TR_TZ)
    return f"{d.day} {TR_MONTHS[d.month - 1]} {d:%H:%M}"


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
            }
        if f.get("location"):
            g["locations"].append(f["location"])
        elif f.get("section_index") is not None:
            g["sections"].add(f["section_index"] + 1)
    order = {"error": 0, "warning": 1, "info": 2}
    cards = sorted(
        groups.values(), key=lambda g: (order.get(g["severity"], 9), -len(g["locations"]))
    )
    for c in cards:
        c["sections"] = sorted(c["sections"])
    return {"summary": report["summary"], "ruleset": report["ruleset"], "cards": cards}


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
    db = Database(settings.db_path)
    mailer = mailer or make_mailer(settings)
    runner = JobRunner(db, settings)
    rulesets = discover_rulesets(settings.rulesets_dir)
    # Örnek kural seti en sona: pilotta varsayılan seçim gerçek kılavuz olsun.
    ordered_rulesets = sorted(rulesets.values(), key=lambda r: (r.id == "example", r.name))
    login_page: PageSpec | None = (
        page_spec(ordered_rulesets[0].rules) if ordered_rulesets else None
    )
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["when"] = format_when
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
            token = pre_csrf(request)
            resp = render(request, "login.html", csrf=token, page=login_page,
                          domains=settings.allowed_domains, error=None)
            set_pre_csrf(resp, token)
            return resp
        jobs = db.recent_jobs(user.email)
        return render(request, "upload.html", user=user, rulesets=ordered_rulesets,
                      jobs=jobs, max_mb=settings.max_upload_bytes // (1024 * 1024),
                      retention=int(settings.retention_hours))

    @app.post("/login", response_class=HTMLResponse)
    async def login(request: Request) -> HTMLResponse:
        form = await request.form()
        check_csrf(request.cookies.get(PRE_CSRF_COOKIE, ""), str(form.get("csrf", "")))
        email = str(form.get("email", "")).strip().lower()
        token = pre_csrf(request)

        def fail(msg: str) -> HTMLResponse:
            resp = render(request, "login.html", status=400, csrf=token, page=login_page,
                          domains=settings.allowed_domains, error=msg, email=email)
            set_pre_csrf(resp, token)
            return resp

        if not EMAIL_RE.fullmatch(email):
            return fail("Geçerli bir e-posta adresi yazın.")
        if not domain_allowed(email):
            return fail(
                "Pilot süresince yalnızca üniversite e-posta adresleriyle giriş yapılabilir."
            )
        if db.login_requests_since(email, time.time() - 3600) >= settings.login_requests_per_hour:
            return fail("Çok fazla giriş isteği gönderildi. Bir saat sonra yeniden deneyin.")
        login_token = secrets.token_urlsafe(32)
        db.add_login_token(_hash(login_token), email, settings.login_token_minutes * 60)
        mailer.send_login_link(email, f"{settings.base_url}/auth?token={login_token}")
        return render(request, "login_sent.html", email=email,
                      minutes=int(settings.login_token_minutes))

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
        if db.active_jobs(user.email) >= settings.max_active_jobs:
            raise HTTPException(429, "Aynı anda en fazla iki denetim yapılabilir.")
        if db.jobs_since(user.email, time.time() - 86400) >= settings.max_daily_jobs:
            raise HTTPException(429, "Günlük denetim sınırına ulaştınız. Yarın yeniden deneyin.")

        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():  # bellekte, sınırla; diske yazılmaz
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise HTTPException(413, "Dosya çok büyük.")
            chunks.append(chunk)
        if size == 0:
            raise HTTPException(400, "Dosya boş.")
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
        view = report_view(json.loads(job.report)) if job.report else None
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
        if job.status != "done" or ruleset is None or not job.source_sha256:
            raise HTTPException(409, "Bu denetim için kopya üretilemiyor.")
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise HTTPException(413, "Dosya çok büyük.")
            chunks.append(chunk)
        data = b"".join(chunks)
        if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), job.source_sha256):
            raise HTTPException(409, "Bu, denetlenen dosya değil. Aynı dosyayı seçin ya da "
                                     "yeni dosya için yeni bir denetim başlatın.")
        result = await run_in_threadpool(runner.make_output, kind,  # type: ignore[arg-type]
                                         job_id, data, str(ruleset.path))
        del data, chunks
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
        ):
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        if exc.status_code == 401:
            return RedirectResponse("/", status_code=303)
        messages = {403: "Oturum doğrulaması başarısız. Sayfayı yenileyip yeniden deneyin.",
                    404: "Aradığınız sayfa bulunamadı ya da süresi doldu."}
        return render(request, "error.html", status=exc.status_code,
                      message=messages.get(exc.status_code, str(exc.detail)))

    return app
