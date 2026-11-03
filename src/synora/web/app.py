"""A9 — Web API ve sayfalar.

Akış: e-posta ile tek kullanımlık giriş → .docx yükle → bellekte, ayrı süreçte denetim →
rapor ekranı. Tez dosyası diske yazılmaz; rapor saklama süresi sonunda silinir.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import smtplib
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
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
from synora.web.access import AccessVerifier
from synora.web.db import TR_TZ, Database, Job, tr_day
from synora.web.limits import UPLOAD_TOO_LARGE, SlotCounter, read_body
from synora.web.mailer import Mailer, make_mailer
from synora.web.pipeline import REPORT_TOO_LARGE, run_pipeline
from synora.web.presentation import PageSpec, RuleTile, page_spec, rule_tiles
from synora.web.settings import Settings
from synora.web.worker import JobRunner, NoProcessSlot
from synora.word import build_docx

HERE = Path(__file__).resolve().parent
HERO_SHOT = HERE / "static" / "rapor-once-sonra.webp"  # varsa ana sayfada barkodun yerini alır
SESSION_COOKIE = "synora_session"
PRE_CSRF_COOKIE = "synora_pre"
# Kayıtta onaylanan aydınlatma metninin sürümü; metin değişince artırılır.
TERMS_VERSION = "aydinlatma-taslak-2026-11"
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
# synora.parse'ın verdiği paragraf kimlikleri: w14:paraId (1–8 onaltılık) ya da "p<sıra>".
PARA_ID_RE = re.compile(r"p[0-9]{1,9}|[0-9A-Fa-f]{1,8}")
# Türkçe klavyeyle yazılmış adres (/yonetım, /GİRİŞ) bilinen bir sayfaya karşılık geliyorsa oraya
# yönlendirilir. Yalnızca bu listeye: başka hedef üretilemez (açık yönlendirme yok).
TR_KEYBOARD = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iissgguuoocc")
KNOWN_PAGES = frozenset({"/yonetim", "/giris", "/kayit", "/aydinlatma", "/fiyatlandirma",
                         "/yukle", "/demo"})

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)
OUTPUT_FILES = {"fixed": "sontez-duzeltilmis.docx", "annotated": "sontez-yorumlu.docx"}
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OUTPUT_ERRORS = {
    "NOTHING_TO_FIX": "Bu belgede otomatik düzeltilebilecek bir bulgu yok.",
    "TIMEOUT": "İşlem süre sınırını aştı. Raporu kullanarak Word'de düzeltebilirsiniz.",
}
MAX_USER_ROLES = 2000
# Yönetici anahtarı oturum başına bu kadar geçerli (açık bırakılan bilgisayar için).
ADMIN_UNLOCK_SECONDS = 2 * 3600
# Yönetim işlemi sonrası ileti: adreste yalnızca bu kodlar taşınır, e-posta ya da serbest metin yok.
ADMIN_STATUS = {
    "oturum": ("Hesabın oturumları kapatıldı.", False),
    "oturum-yok": ("Hesabın açık oturumu yok.", False),
    "silindi": ("Hesap ve bağlı veriler silindi.", False),
    "onay": ("Onay e-postası eşleşmedi; hesap silinmedi.", True),
    "yok": ("Kayıt bulunamadı ya da işlem zaten yapılmış.", True),
    "okundu": ("Öneri okundu işaretlendi.", False),
    "oneri-silindi": ("Öneri silindi.", False),
    "okunmadi": ("Öneri okunmadı işaretlendi.", False),
    "eklendi": ("Hesap eklendi. Kişi kayıt olurken aydınlatma metnini kendisi onaylayacak.", False),
    "var": ("Bu adresle kayıtlı bir hesap zaten var.", True),
    "gecersiz": ("Geçerli bir üniversite e-posta adresi yazın.", True),
    "askida": ("Hesap askıya alındı, oturumları kapatıldı.", False),
    "etkin": ("Hesap yeniden etkinleştirildi.", False),
    "yonetici": ("Yönetici hesabı askıya alınamaz.", True),
}
ADMIN_ACTIONS = {
    "session_end": "Oturum kapatma",
    "account_add": "Hesap ekleme",
    "account_delete": "Hesap silme",
    "account_suspend": "Hesap askıya alma",
    "account_activate": "Hesap etkinleştirme",
    "suggestion_read": "Öneri okundu",
    "suggestion_unread": "Öneri okunmadı",
    "suggestion_delete": "Öneri silme",
}
ADMIN_PAGE_SIZE = 50
UNLIMITED_PER_MINUTE = 1_000_000
FORM_READ_SECONDS = 10.0
SUGGESTION_ID_RE = re.compile(r"[0-9]{1,18}")
PAGE_NUMBER_RE = re.compile(r"[1-9][0-9]{0,8}")
# Rol seçim listesi (arayüz sırası); yalnızca synora.check.USER_ROLES içindekiler.
ROLE_CHOICES = [r for r in (
    "heading_1", "heading_2", "heading_3", "body", "front_matter", "block_quote", "list_item",
    "figure_caption", "table_caption", "reference_entry") if r in {u.value for u in USER_ROLES}]
JOB_ERRORS = {
    "TIMEOUT": "Denetim süre sınırını aştı. Belge çok büyük ya da karmaşık olabilir.",
    "INTERNAL": "Beklenmeyen bir hata oluştu. Dosyanızı Word'de açıp yeniden kaydedip deneyin.",
    "INTERRUPTED": "Sunucu yeniden başlatıldığı için denetim tamamlanamadı. Yeniden yükleyin.",
    REPORT_TOO_LARGE: "Belgede rapora sığmayacak kadar çok biçim farkı var.",
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _same_token(expected: str, provided: str) -> bool:
    """Bayt karşılaştırması: str sürümü ASCII dışı girdide TypeError fırlatır."""
    return hmac.compare_digest(expected.encode(), provided.encode())


def client_network(ip: str) -> str:
    """Hız sınırı anahtarı: IPv6 istemcisi /64 ağının tamamını kullanabilir, tek istemci sayılır."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return ip


@dataclass(frozen=True)
class User:
    email: str
    csrf: str
    session_hash: str


class RateLimiter:
    """Anahtar (istemci özeti) başına saatlik ve site geneli dakikalık istek sınırı.

    Bellek içi. Reddedilen yeni anahtar saklanmaz, penceresi geçen anahtarlar düşer; sözlük
    site geneli sınırın izin verdiği kadar (saatte per_minute × 60 anahtar) büyüyebilir.
    """

    def __init__(self, per_key_hour: int, per_minute: int) -> None:
        self.per_key_hour = per_key_hour
        self.per_minute = per_minute
        self._hits: dict[str, list[float]] = {}
        self._recent: list[float] = []

    def __len__(self) -> int:
        return len(self._hits)

    def exhausted(self, key: str, now: float | None = None) -> bool:
        """Saatlik hak bitti mi? Sayaca dokunmaz."""
        now = time.time() if now is None else now
        recent = [t for t in self._hits.get(key, []) if t > now - 3600]
        return len(recent) >= self.per_key_hour

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        hits = [t for t in self._hits.get(key, []) if t > now - 3600]
        self._recent = [t for t in self._recent if t > now - 60]
        allowed = len(hits) < self.per_key_hour and len(self._recent) < self.per_minute
        if allowed:
            hits.append(now)
            self._recent.append(now)
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        if len(self._hits) > 1000:
            for stale in [k for k, v in self._hits.items() if v[-1] <= now - 3600]:
                del self._hits[stale]
        return allowed


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


TR_MONTHS =["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


TR_MONTHS_LONG = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
                  "Eylül", "Ekim", "Kasım", "Aralık"]


def format_date(ts: float) -> str:
    """LaTeX'teki bugünün tarihi biçimi: '12 Ekim 2026'."""
    d = datetime.fromtimestamp(ts, TR_TZ)
    return f"{d.day} {TR_MONTHS_LONG[d.month - 1]} {d.year}"


def format_when(ts: float) -> str:
    d = datetime.fromtimestamp(ts, TR_TZ)
    return f"{d.day} {TR_MONTHS[d.month - 1]} {d:%H:%M}"


def format_uptime(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} dk"
    hours = minutes // 60
    return f"{hours} sa" if hours < 24 else f"{hours // 24} gün {hours % 24} sa"


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
                "omitted": 0,
            }
        omitted = f.get("omitted", 0)  # raporda tutulmayan aynı türden bulgular
        g["count"] += 1 + omitted
        g["omitted"] += omitted
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
            "finding_count": sum(c["count"] for c in cards),
            "dropped_findings": report.get("dropped_findings", 0),
            "blocks": blocks, "outline": _outline(blocks),
            "role_choices": [(r, _role_name(r)) for r in ROLE_CHOICES],
            "checked": report.get("checked_rules") or [],  # eski raporlarda alan yok
            "editable": sum(1 for b in blocks if "pid" in b)}


def finding_exists(report: dict[str, Any], rule_id: str, para_id: str) -> bool:
    """Oy yalnızca bu raporda gerçekten geçen bulguya verilebilir (yanlış alarm ölçüsü bozulmasın).
    Paragraf verilmezse kartın tamamına verilmiş sayılır."""
    return any(f["rule_id"] == rule_id and (not para_id or f.get("para_id") == para_id)
               for f in report["findings"])


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
    # 1840 denemelik bozma ölçümünden (2026-10-20: yakalama %97,1).
    # Sayılar yalnızca üniversite tez kılavuzlarını kapsar (örnek küme ve dergi şablonları hariç).
    thesis_sets = [r for r in rulesets.values() if r.rules.kind == "thesis" and r.rules.institution]
    landing_stats = {
        "formats": len(thesis_sets),
        "universities": len({r.rules.institution for r in rulesets.values()
                             if r.rules.institution and r.rules.kind == "thesis"}),
        "accuracy": "%97,1",
        "max_mb": settings.max_upload_bytes // (1024 * 1024),
        "daily_jobs": settings.max_daily_jobs,
        "job_minutes": int(settings.job_timeout_seconds // 60),
        "hero_shot": HERO_SHOT.is_file(),
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
        if not provided or not _same_token(expected, provided):
            raise HTTPException(403, "CSRF")

    def pre_csrf(request: Request) -> str:
        return request.cookies.get(PRE_CSRF_COOKIE) or secrets.token_urlsafe(24)

    def set_pre_csrf(response: Response, token: str) -> None:
        response.set_cookie(PRE_CSRF_COOKIE, token, httponly=True, samesite="strict",
                            secure=settings.secure_cookies, max_age=3600)

    def render(request: Request, name: str, status: int = 200, **ctx: Any) -> HTMLResponse:
        # Üst çubukta "Yönetim" bağlantısı. Demo kipinde adres doğrulanmadığından gösterilmez: aksi
        # hâlde bir adresle oturum açan, onun yönetici olduğunu öğrenirdi.
        ctx["is_admin"] = settings.email_verification and admin_allowed(ctx.get("user"))
        return templates.TemplateResponse(request, name, ctx, status_code=status)

    # Yönetici anahtarı girilmiş oturumlar: oturum özeti → bitiş. Bellekte; yeniden başlatmada
    # anahtar yeniden sorulur.
    admin_unlocked: dict[str, float] = {}

    def admin_allowed(user: User | None) -> bool:
        return user is not None and settings.admin_enabled and user.email in settings.admin_emails

    # Access ayarlıysa panel kimliği yalnızca JWT'den gelir; oturum ve anahtar yok sayılır.
    access = (AccessVerifier(settings.access_team_domain, settings.access_aud)
              if settings.access_enabled else None)
    started_at = time.time()
    # Access kipinde uygulama oturumu yok: CSRF değeri süreç başına rastgele sırla e-postadan türer.
    admin_csrf_secret = secrets.token_bytes(32)

    def access_admin(request: Request, verifier: AccessVerifier) -> User | None:
        token = request.headers.get("cf-access-jwt-assertion")
        email = verifier.email(token)
        if email is None:
            if token:  # Access'ten geçen istekte olmamalı: atlatma denemesi ya da yanlış ayar
                log_event("admin.access_invalid")
            return None
        if email not in settings.admin_emails:
            log_event("admin.access_denied", hash=_hash(email)[:16])
            return None
        csrf = hmac.new(admin_csrf_secret, email.encode(), hashlib.sha256).hexdigest()
        return User(email=email, csrf=csrf, session_hash="")

    def key_form_allowed(user: User) -> bool:
        """Demo kipinde adres doğrulanmaz: form herkese aynı görünür, aksi hâlde 200/404 farkı
        yöneticinin adresini ele verirdi. Paneli yine yalnızca liste + anahtar açar."""
        return admin_allowed(user) or (not settings.email_verification and settings.admin_enabled)

    def admin_open(user: User) -> bool:
        now = time.time()
        for stale in [k for k, until in admin_unlocked.items() if until <= now]:
            del admin_unlocked[stale]
        return user.session_hash in admin_unlocked

    # Demo kipinde adres doğrulanmadığı için aynı e-postayla başkası da girebilir: rapor yalnızca
    # onu başlatan oturumda listelenir ve açılır. Doğrulamalı kipte adres sahipliği kanıtlıdır.
    session_bound = not settings.email_verification

    def own_job(user: User, job_id: str, *, with_report: bool = True) -> Job:
        if not JOB_ID_RE.fullmatch(job_id):
            raise HTTPException(404)
        job = db.get_job(job_id) if with_report else db.get_job_meta(job_id)
        if job is None or not hmac.compare_digest(job.email, user.email) or expired(job):
            raise HTTPException(404)
        if session_bound and not hmac.compare_digest(job.session_hash or "", user.session_hash):
            raise HTTPException(404)
        return job

    async def load_job(user: User, job_id: str) -> Job:
        """Rapor megabaytlarca olabilir: okuma olay döngüsünü tutmasın."""
        return await run_in_threadpool(own_job, user, job_id)

    async def parse_report(job: Job) -> dict[str, Any]:
        return dict(await run_in_threadpool(json.loads, job.report or "{}"))

    def visible_jobs(user: User) -> list[Job]:
        return db.recent_jobs(user.email,
                              session_hash=user.session_hash if session_bound else None)

    def expired(job: Job) -> bool:
        # Temizlik görevi 10 dakikada bir çalışır; "24 saat sonra silinir" sözü okurken de tutulur.
        return job.created_at < time.time() - settings.retention_hours * 3600

    # Kopya üretimi istek içinde çalışır (ayrı süreç, 2 GB'a kadar).
    outputs_running = SlotCounter()

    def check_active(email: str) -> None:
        if db.active_jobs(email) + outputs_running.of(email) >= settings.max_active_jobs:
            raise HTTPException(429, "Aynı anda en fazla iki denetim yapılabilir.")

    def check_output_capacity(email: str) -> None:
        check_active(email)
        if outputs_running.total() >= settings.workers:
            raise HTTPException(503, SERVER_BUSY)
        # Tek hesap tüm alt süreç yuvalarını tutmasın.
        if outputs_running.of(email) >= max(1, settings.workers - 1):
            raise HTTPException(429, "Aynı anda en fazla iki denetim yapılabilir.")

    copy_limiter = RateLimiter(settings.copies_per_hour, settings.copies_per_minute)

    def check_copy_quota(email: str) -> None:
        if not copy_limiter.allow(_hash(email)[:16]):
            raise HTTPException(429, "Kısa sürede çok fazla kopya istendi. Bir saat sonra "
                                     "yeniden deneyin.")

    def check_job_limits(email: str) -> None:
        """Yeni yükleme: eşzamanlı ve günlük sınır (kopya ve yeniden denetim günlük sayılmaz)."""
        check_active(email)
        if db.jobs_since(email, time.time() - 86400) >= settings.max_daily_jobs:
            raise HTTPException(429, "Günlük denetim sınırına ulaştınız. Yarın yeniden deneyin.")

    # Gövdesi okunmakta olan yüklemeler (her biri bellekte 100 MB'a kadar). Kuyruk ve iş sayısı
    # ancak gövde okunduktan sonra artar; bu sayaç olmadan paralel isteklerin hepsi okunurdu.
    uploads_running = SlotCounter()
    upload_timeouts = RateLimiter(settings.upload_timeouts_per_hour, UNLIMITED_PER_MINUTE)

    async def read_upload(request: Request, email: str) -> bytes:
        """Yükleme gövdesini tek geçitten okur: bellekte, yuvayla, boyut ve süre sınırıyla."""
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes:
            raise HTTPException(413, UPLOAD_TOO_LARGE)
        if uploads_running.total() >= settings.max_uploads_in_flight:
            raise HTTPException(503, SERVER_BUSY)
        if uploads_running.of(email) >= settings.max_active_jobs:
            raise HTTPException(429, "Aynı anda en fazla iki denetim yapılabilir.")
        client = _client_key(request)
        if upload_timeouts.exhausted(client):
            raise HTTPException(429, "Çok fazla yükleme yarıda kaldı. Bir saat sonra yeniden "
                                     "deneyin.")
        with uploads_running.hold(email):
            try:
                return await read_body(request.stream(), max_bytes=settings.max_upload_bytes,
                                       grace_seconds=settings.upload_grace_seconds,
                                       min_bytes_per_second=settings.upload_min_bytes_per_second,
                                       max_seconds=settings.upload_max_seconds)
            except HTTPException as exc:
                if exc.status_code == 408:
                    upload_timeouts.allow(client)
                raise

    async def small_body(request: Request, content_type: str, limit: int) -> bytes:
        """Küçük, beklenen türde gövde; büyüğü okumadan reddedilir."""
        if request.headers.get("content-type", "").split(";")[0].strip() != content_type:
            raise HTTPException(415, "Desteklenmeyen istek biçimi.")
        length = request.headers.get("content-length", "")
        if not length.isdigit() or int(length) > limit:
            raise HTTPException(413, "İstek çok büyük.")
        return await read_body(request.stream(), max_bytes=limit,
                               grace_seconds=FORM_READ_SECONDS, min_bytes_per_second=1,
                               max_seconds=FORM_READ_SECONDS)

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

    def check_queue(size: int) -> None:
        if (runner.queued() >= settings.max_queued_jobs
                or runner.held_bytes() + size > settings.max_queued_bytes):
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
        """Panel kartları ve son denetimler tablosu. Tam rapor değil, yalnızca özet okunur."""
        jobs = [j for j in visible_jobs(user) if not expired(j)]
        rows: list[dict[str, Any]] = []
        latest: dict[str, Any] | None = None
        frequent: list[tuple[str, int]] = []
        for j in jobs:
            stats = json.loads(j.stats) if j.status == "done" and j.stats else None
            findings_n = stats["findings"] if stats else None
            if stats and latest is None:
                latest = {"id": j.id, "when": format_when(j.created_at),
                          "errors": stats["errors"], "warnings": stats["warnings"],
                          "fixable": stats["fixable"], "findings": findings_n,
                          "ruleset_name": _ruleset_name(j.ruleset),
                          "ruleset": j.ruleset, "hours_left": _hours_left(j)}
                frequent = [(rule_label(rid), n) for rid, n in
                            sorted(stats["rule_counts"].items(), key=lambda kv: -kv[1])[:3]]
            rows.append({"id": j.id, "when": format_when(j.created_at), "status": j.status,
                         "ruleset_name": _ruleset_name(j.ruleset), "findings": findings_n,
                         "hours_left": _hours_left(j)})
        shown = (rulesets.get((latest or {}).get("ruleset", ""))
                 or rulesets.get(settings.default_ruleset)
                 or (ordered_rulesets[0] if ordered_rulesets else None))
        # Kâğıt ve yazı tipi kendini anlatır; ölçüler etiketsiz anlamsız ("3 cm" neyin?).
        chips = [t.value if t.label in ("Kâğıt", "Yazı tipi") else f"{t.label} {t.value}"
                 for t in rule_tiles(shown.rules)[:7]] if shown else []
        # Panelden sürükle-bırak yükleme varsayılan kılavuzla yapılır; kart adını gösterir.
        default = ordered_rulesets[0] if ordered_rulesets else None
        return {"rows": rows, "latest": latest, "frequent": frequent, "chips": chips,
                "ruleset_name": shown.name if shown else "—",
                "template_href": f"/sablon/{shown.id}/sablon.docx" if shown else "/",
                "upload_ruleset": default.id if default else "",
                "upload_ruleset_name": default.name if default else "",
                "max_bytes": settings.max_upload_bytes, "session_only": session_bound}

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
        latest_done = next((j.id for j in visible_jobs(user)
                            if j.status == "done" and not expired(j)), None)
        return render(request, "upload.html", user=user, active="yukle",
                      rulesets=ordered_rulesets, ruleset_groups=ruleset_groups,
                      counts=landing_stats,
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
        name = f"sontez-{ruleset_id}-sablon.docx"
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
        name = f"sontez-{ruleset_id}-latex.zip"
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

    # İstemci başına istek sınırı. Bellek içi ve hash'li: ham IP hiçbir yerde
    # tutulmaz, pencere dolunca kayıt düşer. Uygulamaya yalnızca 127.0.0.1 (tünel/vekil)
    # üzerinden ulaşılır; IP, öndeki vekilin koyduğu başlıktan (client_ip_header) okunur.
    def _client_key(request: Request) -> str:
        header = settings.client_ip_header
        ip = ((request.headers.get(header) if header else None)
              or (request.client.host if request.client else "?"))
        return hashlib.sha256(client_network(ip).encode()).hexdigest()[:16]

    def make_rate_limiter(per_ip_hour: int, per_minute: int) -> Callable[[Request], bool]:
        limiter = RateLimiter(per_ip_hour, per_minute)
        return lambda request: limiter.allow(_client_key(request))

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
        if not provided or not _same_token(expected, provided):
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
        if mode == "register" and form.get("kvkk") != "1":
            return fail("Devam etmek için aydınlatma metnini onaylayın.")
        if not settings.email_verification:
            # Demo kipi: adres sahipliği doğrulanmadan oturum açılır (bkz. Settings). E-posta
            # gönderilmediği için adres başına sınır yok; başkası bu adresi kilitleyemesin.
            if db.is_suspended(email):
                return fail("Bu adresle giriş şu anda kapalı.")
            if mode == "register":
                db.register_user(email, TERMS_VERSION)
            elif db.user_consent(email) is None:
                return fail("Bu adres kayıtlı değil. Önce kayıt olun.")
            return open_session(email)

        def link_sent() -> HTMLResponse:
            return render(request, "login_sent.html", email=email, mode=mode,
                          minutes=int(settings.login_token_minutes))

        if db.is_suspended(email):
            return link_sent()  # aynı yanıt, e-posta yok: hesap durumu dışarıdan anlaşılmasın
        if db.login_requests_since(email, time.time() - 3600) >= settings.login_requests_per_hour:
            return fail("Çok fazla giriş isteği gönderildi. Bir saat sonra yeniden deneyin.")
        login_token = secrets.token_urlsafe(32)
        token_hash = _hash(login_token)
        # Onayı olmayan adres giriş formundan gelse de bağlantı onay sayfasına çıkar. Hata vermek
        # yerine böyle yapılır: adresin kayıtlı olup olmadığı dışarıdan anlaşılmasın.
        needs_consent = mode == "register" or db.user_consent(email) is None
        db.add_login_token(token_hash, email, settings.login_token_minutes * 60,
                           consent=TERMS_VERSION if needs_consent else None)
        try:
            # smtplib eşzamanlı ve 20 sn bekleyebilir: olay döngüsünü kilitlemesin.
            await run_in_threadpool(mailer.send_login_link, email,
                                    f"{settings.base_url}/auth?token={login_token}")
        except (smtplib.SMTPException, OSError) as exc:
            db.delete_login_token(token_hash)  # gönderilemeyen bağlantı sınırdan düşmesin
            log_event("mail.failed", code=type(exc).__name__)
            return auth_form(request, mode, status=503, email=email,
                             error="E-posta gönderilemedi. Birkaç dakika sonra yeniden deneyin.")
        return link_sent()

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
        iletişim GitHub'ın özel güvenlik bildirimi (advisory) formu üzerinden."""
        body = (
            "Contact: https://github.com/berkcicekk/synora/security/advisories/new\n"
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
            "# Sontez\n\n"
            "> Sontez, .docx tezleri üniversitenin resmî yazım kılavuzuna göre denetleyen "
            "ve biçim hatalarını düzelten ücretsiz bir web aracıdır. "
            f"{landing_stats['universities']} üniversitenin {landing_stats['formats']} kural seti "
            "hazır yüklüdür.\n\n"
            "Önemli: Sontez tezin metnini ASLA değiştirmez ve hiçbir yapay zekâ modeli tez "
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
            "Sontez checks Turkish university theses (.docx) against the institution's "
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
        account = db.login_token_email(_hash(token)) if valid else None
        resp = render(request, "auth_confirm.html", status=status or (200 if valid else 400),
                      token=token, csrf=csrf, valid=valid, needs_consent=needs_consent,
                      account=account,
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
        admin_unlocked.pop(user.session_hash, None)
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    # --- Yönetim paneli -----------------------------------------------------------------------

    def _day_label(day: str) -> str:
        return f"{int(day[8:])} {TR_MONTHS[int(day[5:7]) - 1]}"

    def account_rows(now: float, *, limit: int, offset: int = 0,
                     query: str = "") -> list[dict[str, Any]]:
        return [{"email": e, "joined": format_when(c), "online": bool(o), "jobs": int(n),
                 "suspended": s is not None, "pending": v is None,
                 "is_admin": e in settings.admin_emails}
                for e, c, v, s, o, n in db.admin_accounts(now, limit=limit, offset=offset,
                                                          query=query)]

    def suggestion_rows(limit: int, unread_only: bool = False) -> list[dict[str, Any]]:
        return [{"id": i, "when": format_when(t), "page": p or "—", "email": e or "—",
                 "message": m, "read": r is not None}
                for i, t, p, e, m, r in db.admin_suggestions(limit, unread_only)]

    def admin_overview() -> dict[str, Any]:
        """Özet: sayılar, 14 gün, son hesaplar ve öneriler, en sık kurallar. Rapor içeriği yok."""
        now = time.time()
        days = [tr_day(now - k * 86400) for k in range(14)]  # bugün başta
        jobs_by_day = db.daily_jobs(days[-1])
        regs: dict[str, int] = {}
        for ts in db.registrations_since(now - 15 * 86400):
            regs[tr_day(ts)] = regs.get(tr_day(ts), 0) + 1
        peak = max([1, *jobs_by_day.values()])
        activity = [{"label": _day_label(d), "users": regs.get(d, 0), "jobs": jobs_by_day.get(d, 0),
                     "w": round(jobs_by_day.get(d, 0) / peak * 100)} for d in days]
        rules = db.rule_totals()
        rule_peak = max([1, *(n for _, n, _ in rules)])
        return {
            "counts": db.admin_counts(now),
            "activity": activity,
            "accounts": account_rows(now, limit=5),
            "suggestions": suggestion_rows(5),
            "unread": db.unread_suggestions(),
            "rules": [{"label": rule_label(r), "id": r, "n": n, "wrong": w,
                       "w": round(n / rule_peak * 100)} for r, n, w in rules],
            "session_hours": int(settings.session_hours),
        }

    def admin_accounts_page(request: Request) -> dict[str, Any]:
        raw = request.query_params.get("sayfa", "1")
        total = db.account_total()
        pages = max(1, (total + ADMIN_PAGE_SIZE - 1) // ADMIN_PAGE_SIZE)
        page = min(int(raw), pages) if PAGE_NUMBER_RE.fullmatch(raw) else 1
        counts = db.admin_counts(time.time())
        return {"accounts": account_rows(time.time(), limit=ADMIN_PAGE_SIZE,
                                         offset=(page - 1) * ADMIN_PAGE_SIZE),
                "total": total, "page": page, "pages": pages, "query": "",
                "pending": counts["pending"], "suspended": counts["suspended"]}

    def admin_suggestions_page(request: Request) -> dict[str, Any]:
        unread_only = request.query_params.get("filtre") == "okunmamis"
        return {"suggestions": suggestion_rows(100, unread_only), "unread_only": unread_only,
                "unread": db.unread_suggestions()}

    def admin_usage_page() -> dict[str, Any]:
        now = time.time()
        return {
            "usage": [{"name": ruleset_name(r), "id": r, "total": d + f, "failed": f,
                       "rate": round(d / (d + f) * 100),
                       "avg": f"{s / d:.1f} sn".replace(".", ",") if d else "—"}
                      for r, d, f, s in db.usage_since(tr_day(now - 29 * 86400))],
            "false_alarms": [{"name": ruleset_name(r), "version": v, "label": rule_label(i),
                              "id": i, "wrong": w, "votes": w + o,
                              "rate": round(w / (w + o) * 100)}
                             for r, v, i, w, o in db.false_alarms()],
        }

    def ruleset_name(ruleset_id: str) -> str:
        found = rulesets.get(ruleset_id)
        return found.name if found else ruleset_id

    def admin_system(now: float) -> dict[str, Any]:
        """Çalışma durumu. Yalnızca sayılar ve hata kodları; iş kimliği, e-posta ya da rapor yok."""
        size = 0
        for path in (settings.db_path, Path(f"{settings.db_path}-wal")):
            with suppress(OSError):
                size += path.stat().st_size
        return {
            "build": settings.build or "—",
            "workers_ok": runner.alive(),
            "queue": f"{runner.queued()} / {settings.max_queued_jobs}",
            "uploads": f"{uploads_running.total()} / {settings.max_uploads_in_flight}",
            "db": f"{size / (1024 * 1024):.1f} MB".replace(".", ","),
            "uptime": format_uptime(now - started_at),
            "errors": [{"code": c, "n": n, "message": job_error_message(c)}
                       for c, n in db.job_errors(now - 86400)],
        }

    def admin_key_form(request: Request, user: User, status: int = 200,
                       error: str | None = None) -> HTMLResponse:
        return render(request, "admin_key.html", status=status, user=user, error=error,
                      retention=int(settings.retention_hours))

    # Anahtar denemesi: istemci başına saatte 5, sunucu genelinde dakikada 20.
    admin_key_rate_ok = make_rate_limiter(5, 20)

    def admin_render(request: Request, user: User, template: str, section: str,
                     data: dict[str, Any]) -> HTMLResponse:
        return render(request, template, user=user, section=section, admin=data,
                      notice=ADMIN_STATUS.get(request.query_params.get("durum", "")),
                      access_login=access is not None, retention=int(settings.retention_hours))

    def admin_view(request: Request, template: str, section: str,
                   build: Callable[[], dict[str, Any]]) -> HTMLResponse:
        """Access ya da listedeki e-posta + bu oturumda girilmiş anahtar; diğer herkese 404.
        Sayfa verisi yalnızca yetki doğrulandıktan sonra hazırlanır."""
        if access is not None:
            user = access_admin(request, access)
            if user is None:
                raise HTTPException(404)
        else:
            found = current_user(request)
            if found is None or not key_form_allowed(found):
                raise HTTPException(404)
            if not admin_open(found):
                return admin_key_form(request, found)
            user = found
        log_event("admin.view", hash=_hash(user.email)[:16])
        return admin_render(request, user, template, section, build())

    @app.get("/yonetim", response_class=HTMLResponse)
    def admin_page(request: Request) -> HTMLResponse:
        return admin_view(request, "admin.html", "ozet", admin_overview)

    @app.get("/yonetim/hesaplar", response_class=HTMLResponse)
    def admin_accounts(request: Request) -> HTMLResponse:
        return admin_view(request, "admin_accounts.html", "hesaplar",
                          lambda: admin_accounts_page(request))

    @app.get("/yonetim/oneriler", response_class=HTMLResponse)
    def admin_suggestions(request: Request) -> HTMLResponse:
        return admin_view(request, "admin_suggestions.html", "oneriler",
                          lambda: admin_suggestions_page(request))

    @app.get("/yonetim/kullanim", response_class=HTMLResponse)
    def admin_usage(request: Request) -> HTMLResponse:
        return admin_view(request, "admin_usage.html", "kullanim", admin_usage_page)

    @app.get("/yonetim/sistem", response_class=HTMLResponse)
    def admin_system_view(request: Request) -> HTMLResponse:
        return admin_view(request, "admin_system.html", "sistem",
                          lambda: admin_system(time.time()))

    @app.get("/yonetim/kayit", response_class=HTMLResponse)
    def admin_log_view(request: Request) -> HTMLResponse:
        return admin_view(request, "admin_log.html", "kayit", lambda: {
            "log": [{"when": format_when(t), "actor": a, "action": ADMIN_ACTIONS.get(c, c),
                     "target": x} for t, a, c, x in db.admin_log(100)]})

    # --- Yönetim işlemleri: yetki → CSRF → işlem; yetkisize gövde okunmadan 404 -----------------

    def admin_actor(request: Request) -> User | None:
        if access is not None:
            return access_admin(request, access)
        user = current_user(request)
        return user if user is not None and admin_allowed(user) and admin_open(user) else None

    async def admin_form(request: Request) -> tuple[User, FormData]:
        """Yönetici ve form. JWT anahtarı ağdan alınabilir: olay döngüsü bloklanmasın."""
        user = await run_in_threadpool(admin_actor, request)
        if user is None:
            raise HTTPException(404)
        form = await small_form(request)
        check_csrf(user.csrf, str(form.get("csrf", "")))
        return user, form

    async def admin_action(request: Request) -> tuple[str, FormData]:
        user, form = await admin_form(request)
        return _hash(user.email)[:16], form

    def admin_done(status: str, page: str, actor: str | None = None,
                   action: str | None = None) -> RedirectResponse:
        if actor and action:
            log_event("admin.action", hash=actor, code=action)
        return RedirectResponse(f"/yonetim/{page}?durum={status}", status_code=303)

    @app.post("/yonetim/hesaplar/ara", response_class=HTMLResponse)
    async def admin_search_accounts(request: Request) -> Response:
        """Arama POST ile: e-posta adres çubuğuna ve aradaki kayıtlara düşmesin."""
        user, form = await admin_form(request)
        query = str(form.get("q", "")).strip()[:190]
        counts = db.admin_counts(time.time())
        return admin_render(request, user, "admin_accounts.html", "hesaplar", {
            "accounts": account_rows(time.time(), limit=ADMIN_PAGE_SIZE, query=query),
            "total": db.account_total(query), "page": 1, "pages": 1, "query": query,
            "pending": counts["pending"], "suspended": counts["suspended"]})

    @app.post("/yonetim/hesap/ekle")
    async def admin_add_account(request: Request) -> Response:
        actor, form = await admin_action(request)
        email = form_email(form, "email")
        if not EMAIL_RE.fullmatch(email) or not domain_allowed(email):
            return admin_done("gecersiz", "hesaplar")
        if not db.add_pending_user(email, actor=actor, target=_hash(email)[:16]):
            return admin_done("var", "hesaplar")
        return admin_done("eklendi", "hesaplar", actor, "account_add")

    @app.post("/yonetim/hesap/askiya-al")
    async def admin_suspend_account(request: Request) -> Response:
        actor, form = await admin_action(request)
        email = form_email(form, "email")
        if email in settings.admin_emails:  # yönetici kendini dışarıda bırakmasın
            return admin_done("yonetici", "hesaplar")
        if not db.set_suspended(email, True, actor=actor, target=_hash(email)[:16]):
            return admin_done("yok", "hesaplar")
        return admin_done("askida", "hesaplar", actor, "account_suspend")

    @app.post("/yonetim/hesap/etkinlestir")
    async def admin_activate_account(request: Request) -> Response:
        actor, form = await admin_action(request)
        email = form_email(form, "email")
        if not db.set_suspended(email, False, actor=actor, target=_hash(email)[:16]):
            return admin_done("yok", "hesaplar")
        return admin_done("etkin", "hesaplar", actor, "account_activate")

    @app.post("/yonetim/oneri/okunmadi")
    async def admin_unread_suggestion(request: Request) -> Response:
        actor, form = await admin_action(request)
        sid = suggestion_id(form)
        if sid is None or not db.mark_suggestion_unread(sid, actor=actor):
            return admin_done("yok", "oneriler")
        return admin_done("okunmadi", "oneriler", actor, "suggestion_unread")

    def form_email(form: FormData, name: str) -> str:
        return str(form.get(name, "")).strip().lower()

    def suggestion_id(form: FormData) -> int | None:
        value = str(form.get("id", ""))
        return int(value) if SUGGESTION_ID_RE.fullmatch(value) else None

    @app.post("/yonetim/hesap/oturum")
    async def admin_end_sessions(request: Request) -> Response:
        actor, form = await admin_action(request)
        email = form_email(form, "email")
        if not db.end_sessions(email, actor=actor, target=_hash(email)[:16]):
            return admin_done("oturum-yok", "hesaplar")
        return admin_done("oturum", "hesaplar", actor, "session_end")

    @app.post("/yonetim/hesap/sil")
    async def admin_delete_account(request: Request) -> Response:
        actor, form = await admin_action(request)
        email = form_email(form, "email")
        if not EMAIL_RE.fullmatch(email):
            return admin_done("yok", "hesaplar")
        if not hmac.compare_digest(form_email(form, "confirm").encode(), email.encode()):
            return admin_done("onay", "hesaplar")
        deleted = await run_in_threadpool(db.delete_account, email, actor=actor,
                                          target=_hash(email)[:16])
        if not deleted:
            return admin_done("yok", "hesaplar")
        return admin_done("silindi", "hesaplar", actor, "account_delete")

    @app.post("/yonetim/oneri/okundu")
    async def admin_read_suggestion(request: Request) -> Response:
        actor, form = await admin_action(request)
        sid = suggestion_id(form)
        if sid is None or not db.mark_suggestion_read(sid, actor=actor):
            return admin_done("yok", "oneriler")
        return admin_done("okundu", "oneriler", actor, "suggestion_read")

    @app.post("/yonetim/oneri/sil")
    async def admin_delete_suggestion(request: Request) -> Response:
        actor, form = await admin_action(request)
        sid = suggestion_id(form)
        if sid is None or not db.delete_suggestion(sid, actor=actor):
            return admin_done("yok", "oneriler")
        return admin_done("oneri-silindi", "oneriler", actor, "suggestion_delete")

    @app.post("/yonetim/anahtar", response_class=HTMLResponse)
    async def admin_unlock(request: Request) -> Response:
        if access is not None:  # Access varken anahtar yöntemi yok
            raise HTTPException(404)
        user = current_user(request)
        if user is None or not key_form_allowed(user):
            raise HTTPException(404)
        form = await small_form(request)
        check_csrf(user.csrf, str(form.get("csrf", "")))
        who = _hash(user.email)[:16]
        if not admin_key_rate_ok(request):
            return admin_key_form(request, user, 429, "Çok fazla deneme yapıldı. Bir saat sonra "
                                                      "yeniden deneyin.")
        key = str(form.get("key", "")).strip()
        key_matches = bool(key) and hmac.compare_digest(_hash(key), settings.admin_key_sha256)
        if not key_matches or not admin_allowed(user):
            log_event("admin.unlock_failed", hash=who)
            return admin_key_form(request, user, 400, "Anahtar yanlış.")
        admin_unlocked[user.session_hash] = time.time() + ADMIN_UNLOCK_SECONDS
        log_event("admin.unlock", hash=who)
        return RedirectResponse("/yonetim", status_code=303)

    # --- İşler -------------------------------------------------------------------------------

    @app.post("/jobs")
    async def create_job(request: Request) -> JSONResponse:
        user = require_user(request)
        check_csrf(user.csrf, request.headers.get("x-csrf-token"))
        ruleset = rulesets.get(request.headers.get("x-ruleset", ""))
        if ruleset is None:
            raise HTTPException(400, "Kural seti bulunamadı.")
        check_job_limits(user.email)
        data = await read_upload(request, user.email)
        require_user(request)  # okunurken hesap silinmiş ya da askıya alınmış olabilir
        if not data:
            raise HTTPException(400, "Dosya boş.")
        # Gövde okunurken paralel istekler aynı kontrolü geçmiş olabilir; buradan sonra await
        # yok, yeniden kontrol ile kayıt arasına başka istek giremez.
        check_job_limits(user.email)
        check_queue(len(data))
        job_id = secrets.token_urlsafe(18)
        db.add_job(job_id, user.email, ruleset.id, user.session_hash)
        runner.submit(job_id, data, str(ruleset.path))
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
                      ruleset=rulesets.get(job.ruleset), retention=int(settings.retention_hours),
                      max_bytes=settings.max_upload_bytes)

    @app.get("/jobs/{job_id}/status")
    def job_status(request: Request, job_id: str) -> JSONResponse:
        job = own_job(require_user(request), job_id, with_report=False)
        return JSONResponse({"status": job.status})

    @app.get("/jobs/{job_id}/report.json")
    def job_report(request: Request, job_id: str) -> Response:
        job = own_job(require_user(request), job_id)
        if not job.report:
            raise HTTPException(404)
        return Response(job.report, media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="sontez-rapor.json"'})

    @app.post("/jobs/{job_id}/delete")
    async def job_delete(request: Request, job_id: str) -> Response:
        user = require_user(request)
        form = await small_form(request)
        check_csrf(user.csrf, str(form.get("csrf", "")))
        own_job(user, job_id, with_report=False)
        db.delete_job(job_id)
        return RedirectResponse("/", status_code=303)

    async def same_file(request: Request, email: str, expected_sha256: str) -> bytes:
        """Sunucu tezi saklamadığından öğrenci aynı dosyayı yeniden gönderir; bellekte okunur,
        yalnızca SHA-256 özeti karşılaştırılır."""
        data = await read_upload(request, email)
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
        job = await load_job(user, job_id)
        if job.status != "done" or not job.report:
            raise HTTPException(409, "Bu denetim için paragraf türü seçilemiyor.")
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
                raise HTTPException(400, "Geçersiz paragraf ya da paragraf türü.")
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
        """Öğrencinin "Bu bulgu yanlış mı?" oyu. Metin alınmaz; yalnızca rule_id ve karar."""
        user = require_user(request)
        check_csrf(user.csrf, request.headers.get("x-csrf-token"))
        job = await load_job(user, job_id)
        form = await small_form(request)
        rule_id = str(form.get("rule_id", ""))
        verdict = str(form.get("verdict", ""))
        para_id = str(form.get("para_id", ""))
        if verdict not in ("wrong", "ok") or not re.fullmatch(r"[a-z0-9_.]{1,64}", rule_id) or (
                para_id and not PARA_ID_RE.fullmatch(para_id)):
            raise HTTPException(400, "Geçersiz geri bildirim.")
        if not job.report or not finding_exists(await parse_report(job), rule_id, para_id):
            raise HTTPException(400, "Geçersiz geri bildirim.")
        if db.feedback_count(job_id) >= 200:  # sınırsız birikme olmasın
            raise HTTPException(429, "Bu denetim için geri bildirim sınırına ulaşıldı.")
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
        check_copy_quota(user.email)
        data = await same_file(request, user.email, job.source_sha256)
        job = await load_job(user, job_id)  # beklerken başka istek yeniden kuyruğa almış olabilir
        if job.status != "done" or not job.report:
            raise HTTPException(409, "Bu denetim zaten yeniden denetleniyor.")
        check_active(user.email)
        check_queue(len(data))
        roles = pending_roles(job, await parse_report(job))
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
        job = await load_job(user, job_id)
        ruleset = rulesets.get(job.ruleset)
        if job.status != "done" or ruleset is None or not job.source_sha256 or not job.report:
            raise HTTPException(409, "Bu denetim için kopya üretilemiyor.")
        check_output_capacity(user.email)
        check_copy_quota(user.email)
        data = await same_file(request, user.email, job.source_sha256)
        # Yuva gövde okunduktan sonra alınır: yavaş yükleme kopya üretimini kilitleyemesin.
        check_output_capacity(user.email)
        # Kopya, ekrandaki raporla aynı rollerle üretilir (kaydedilmiş ama henüz yeniden
        # denetlenmemiş seçimlerle değil).
        roles = applied_roles(await parse_report(job))
        with outputs_running.hold(user.email):
            try:
                result = await run_in_threadpool(
                    runner.make_output, kind,  # type: ignore[arg-type]
                    job_id, data, str(ruleset.path), roles)
            except NoProcessSlot:
                raise HTTPException(503, SERVER_BUSY) from None
        del data
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
        if code == 404 and request.method in ("GET", "HEAD"):
            path = request.scope["path"]
            typed = path.translate(TR_KEYBOARD).lower()
            if typed != path and typed in KNOWN_PAGES:
                return RedirectResponse(typed, status_code=308)
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
