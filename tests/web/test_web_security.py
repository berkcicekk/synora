"""A9 web güvenliği (gece taraması): giriş bağlantısı, oturum, CSRF, yetki, dosya türü sahteciliği,
güvenlik başlıkları, çerez bayrakları, hız sınırları, XSS ve sır saklama.

A9 backend kodu değiştirilmedi. Bulunan açıklar xfail (strict) olarak işaretli; çözüm önerileri
.gece/ONERILER.md, ayrıntı .gece/GUVENLIK_RAPORU.md.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from builders import DOCM_MAIN, XLSX_MAIN, content_types, minimal_parts, zip_parts
from fastapi.testclient import TestClient
from test_web import bad_thesis, csrf_from, login, output, upload, wait_done
from thesis import thesis

from synora.web.app import SESSION_COOKIE, create_app
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

EMAIL = "ogrenci@beun.edu.tr"


def request_link(client: TestClient, mailer: ConsoleMailer, email: str = EMAIL) -> str:
    page = client.get("/")
    res = client.post("/login", data={"email": email, "csrf": csrf_from(page.text)})
    assert res.status_code == 200, res.text
    return mailer.sent[-1][1].split("token=")[1]


def logged_in(client: TestClient) -> bool:
    return "Tezinizi yükleyin" in client.get("/").text


# --- Giriş bağlantısı -------------------------------------------------------------------------


def test_expired_login_link_is_rejected(client: TestClient, mailer: ConsoleMailer) -> None:
    token = request_link(client, mailer)
    confirm = client.get(f"/auth?token={token}")
    csrf = csrf_from(confirm.text)
    db = client.app.state.db  # type: ignore[attr-defined]
    db.execute("UPDATE login_tokens SET expires_at = ?", (time.time() - 1,))
    assert client.get(f"/auth?token={token}").status_code == 400
    res = client.post("/auth", data={"token": token, "csrf": csrf}, follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/auth"
    assert SESSION_COOKIE not in res.cookies
    assert not logged_in(client)


def test_login_link_cannot_be_posted_twice(settings: Settings, mailer: ConsoleMailer) -> None:
    app = create_app(settings, mailer)
    with TestClient(app) as victim, TestClient(app) as attacker:
        token = request_link(victim, mailer)
        csrf = csrf_from(victim.get(f"/auth?token={token}").text)
        victim.post("/auth", data={"token": token, "csrf": csrf}, follow_redirects=False)
        assert logged_in(victim)
        # Bağlantıyı sonradan ele geçiren biri (ör. iletilen e-posta) oturum açamaz.
        a_csrf = csrf_from(attacker.get("/").text)
        res = attacker.post("/auth", data={"token": token, "csrf": a_csrf},
                            follow_redirects=False)
        assert SESSION_COOKIE not in res.cookies
        assert not logged_in(attacker)


def test_invalid_link_page_does_not_echo_token(client: TestClient) -> None:
    probe = "<script>x</script>"
    res = client.get("/auth", params={"token": probe})
    assert res.status_code == 400
    assert probe not in res.text and "&lt;script&gt;" not in res.text


def test_login_link_uses_configured_base_url_not_host_header(client: TestClient,
                                                            mailer: ConsoleMailer) -> None:
    page = client.get("/")
    client.post("/login", data={"email": EMAIL, "csrf": csrf_from(page.text)},
                headers={"Host": "saldirgan.example"})
    assert mailer.sent[-1][1].startswith("http://testserver/auth?token=")


def test_secrets_stored_only_as_hashes(client: TestClient, mailer: ConsoleMailer,
                                       settings: Settings) -> None:
    token = request_link(client, mailer)
    csrf = csrf_from(client.get(f"/auth?token={token}").text)
    client.post("/auth", data={"token": token, "csrf": csrf})
    sid = client.cookies.get(SESSION_COOKIE)
    assert sid
    raw = settings.db_path.read_bytes()
    for wal in settings.db_path.parent.glob("*.db-wal"):
        raw += wal.read_bytes()
    assert token.encode() not in raw
    assert sid.encode() not in raw


# --- Oturum -----------------------------------------------------------------------------------


def test_expired_session_is_logged_out(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    db = client.app.state.db  # type: ignore[attr-defined]
    db.execute("UPDATE sessions SET expires_at = ?", (time.time() - 1,))
    assert not logged_in(client)


def test_logout_invalidates_session_on_server(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    sid = client.cookies.get(SESSION_COOKIE)
    client.post("/logout", data={"csrf": csrf})
    client.cookies.set(SESSION_COOKIE, sid or "")  # çalınmış eski çerez
    assert not logged_in(client)


def test_logout_requires_csrf(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    assert client.post("/logout", data={"csrf": "yanlis"}).status_code == 403
    assert logged_in(client)


# --- Yetki ve CSRF ----------------------------------------------------------------------------


@pytest.fixture
def two_users(settings: Settings, mailer: ConsoleMailer) -> Iterator[tuple[TestClient, TestClient]]:
    app = create_app(settings, mailer)
    with TestClient(app) as alice, TestClient(app) as bob:
        yield alice, bob


def test_delete_requires_csrf_and_ownership(two_users: tuple[TestClient, TestClient],
                                            mailer: ConsoleMailer) -> None:
    alice, bob = two_users
    a_csrf = login(alice, mailer, "alice@beun.edu.tr")
    job_id = upload(alice, a_csrf, thesis())
    wait_done(alice, job_id)
    b_csrf = login(bob, mailer, "bob@beun.edu.tr")
    assert bob.post(f"/jobs/{job_id}/delete", data={"csrf": b_csrf}).status_code == 404
    assert alice.post(f"/jobs/{job_id}/delete", data={"csrf": "yanlis"}).status_code == 403
    assert alice.get(f"/jobs/{job_id}").status_code == 200  # hâlâ duruyor


def test_csrf_token_of_one_user_does_not_work_for_another(
        two_users: tuple[TestClient, TestClient], mailer: ConsoleMailer) -> None:
    alice, bob = two_users
    a_csrf = login(alice, mailer, "alice@beun.edu.tr")
    login(bob, mailer, "bob@beun.edu.tr")
    res = bob.post("/jobs", content=thesis(), headers={"X-CSRF-Token": a_csrf,
                                                       "X-Ruleset": "example"})
    assert res.status_code == 403


@pytest.mark.parametrize("job_id", ["..%2F..%2Fetc%2Fpasswd", "kisa", "a" * 200,
                                    "%27%20OR%201%3D1--aaaaaaaaaa", "ş" * 20])
def test_malformed_job_ids_are_404(client: TestClient, mailer: ConsoleMailer, job_id: str) -> None:
    login(client, mailer)
    assert client.get(f"/jobs/{job_id}").status_code == 404
    assert client.get(f"/jobs/{job_id}/report.json").status_code == 404


def test_cross_site_form_post_without_token_is_rejected(client: TestClient,
                                                        mailer: ConsoleMailer) -> None:
    # Başka siteden gelen form: çerez gider (SameSite=Lax üst düzey POST'ta göndermez ama eski
    # tarayıcılara güvenme), CSRF alanı yoktur.
    login(client, mailer)
    res = client.post("/logout", data={}, headers={"Origin": "https://saldirgan.example"})
    assert res.status_code == 403


# --- Dosya türü sahteciliği -------------------------------------------------------------------


@pytest.mark.parametrize(("data", "code"), [
    (zip_parts({**minimal_parts(), "[Content_Types].xml": content_types(DOCM_MAIN)}),
     "MACRO_ENABLED"),
    (zip_parts({**minimal_parts(), "[Content_Types].xml": content_types(XLSX_MAIN)}), "NOT_DOCX"),
    (b"MZ\x90\x00" + b"\0" * 512, "NOT_A_ZIP"),
    (b"%PDF-1.7\n" + b"\0" * 512, "NOT_A_ZIP"),
], ids=["docm-as-docx", "xlsx-as-docx", "exe", "pdf"])
def test_disguised_files_are_rejected(client: TestClient, mailer: ConsoleMailer,
                                      data: bytes, code: str) -> None:
    csrf = login(client, mailer)
    res = client.post("/jobs", content=data, headers={
        "X-CSRF-Token": csrf, "X-Ruleset": "example",
        # Tarayıcının bildirdiği tür önemsizdir; içerik denetlenir.
        "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"})
    assert res.status_code == 202
    job_id = res.json()["id"]
    assert wait_done(client, job_id) == "failed"
    assert f"Kod: {code}" in client.get(f"/jobs/{job_id}").text


def test_streamed_upload_without_length_is_capped(client: TestClient, mailer: ConsoleMailer,
                                                  settings: Settings) -> None:
    csrf = login(client, mailer)
    chunk = b"0" * (1024 * 1024)

    def body() -> Iterator[bytes]:
        for _ in range(settings.max_upload_bytes // len(chunk) + 2):
            yield chunk

    res = client.post("/jobs", content=body(), headers={"X-CSRF-Token": csrf,
                                                         "X-Ruleset": "example"})
    assert res.status_code == 413


# --- Güvenlik başlıkları ve çerezler ----------------------------------------------------------


def test_security_headers_on_every_kind_of_response(client: TestClient,
                                                    mailer: ConsoleMailer) -> None:
    responses = {
        "landing": client.get("/"),
        "pricing": client.get("/fiyatlandirma"),
        "static": client.get("/static/app.css"),
        "health": client.get("/health"),
        "unknown": client.get("/boyle-bir-sayfa-yok"),
        "redirect": client.get("/jobs/aaaaaaaaaaaaaaaaaaaa", follow_redirects=False),
    }
    csrf = login(client, mailer)
    responses["json_error"] = client.post("/jobs", content=b"", headers={
        "X-CSRF-Token": csrf, "X-Ruleset": "example"})
    responses["not_found_page"] = client.get("/jobs/aaaaaaaaaaaaaaaaaaaa")
    for name, res in responses.items():
        h = res.headers
        assert "default-src 'self'" in h.get("content-security-policy", ""), name
        assert "frame-ancestors 'none'" in h["content-security-policy"], name
        assert h.get("x-content-type-options") == "nosniff", name
        assert h.get("x-frame-options") == "DENY", name
        assert h.get("referrer-policy") == "no-referrer", name
        if name != "static":
            assert h.get("cache-control") == "no-store", name


@pytest.fixture
def prod_client(tmp_path: Path, mailer: ConsoleMailer) -> Iterator[TestClient]:
    root = Path(__file__).resolve().parents[2]
    s = Settings(db_path=tmp_path / "p.db", rulesets_dir=root / "rulesets",
                 base_url="https://testserver", allowed_domains=("beun.edu.tr",), dev=False,
                 isolate_jobs=False, workers=1)
    with TestClient(create_app(s, mailer), base_url="https://testserver") as c:
        yield c


def test_production_cookies_and_hsts(prod_client: TestClient, mailer: ConsoleMailer) -> None:
    first = prod_client.get("/")
    assert "max-age=31536000" in first.headers["strict-transport-security"]
    pre = first.headers["set-cookie"].lower()
    assert "httponly" in pre and "secure" in pre and "samesite=strict" in pre
    token = request_link(prod_client, mailer)
    csrf = csrf_from(prod_client.get(f"/auth?token={token}").text)
    res = prod_client.post("/auth", data={"token": token, "csrf": csrf}, follow_redirects=False)
    session = next(c for c in res.headers.get_list("set-cookie") if c.startswith(SESSION_COOKIE))
    low = session.lower()
    assert "httponly" in low and "secure" in low and "samesite=lax" in low


def test_production_rejects_unlisted_domains(prod_client: TestClient,
                                             mailer: ConsoleMailer) -> None:
    page = prod_client.get("/")
    res = prod_client.post("/login", data={"email": "biri@ornek.com",
                                           "csrf": csrf_from(page.text)})
    assert res.status_code == 400
    assert mailer.sent == []


def test_api_docs_are_disabled(client: TestClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


# --- XSS --------------------------------------------------------------------------------------


def test_reflected_email_is_escaped(client: TestClient, mailer: ConsoleMailer) -> None:
    payload = '"><script>alert(1)</script>@beun.edu.tr'
    page = client.get("/")
    res = client.post("/login", data={"email": payload, "csrf": csrf_from(page.text)})
    assert res.status_code == 400
    assert "<script>alert(1)</script>" not in res.text
    assert mailer.sent == []


# --- Hız ve kaynak sınırları ------------------------------------------------------------------


def test_daily_job_limit(client: TestClient, mailer: ConsoleMailer, settings: Settings) -> None:
    csrf = login(client, mailer)
    db = client.app.state.db  # type: ignore[attr-defined]
    for i in range(settings.max_daily_jobs):
        db.add_job(f"gunluk-is-{i:010d}", EMAIL, "example")
        db.finish_job(f"gunluk-is-{i:010d}", report=None, error_code="INTERNAL")
    res = client.post("/jobs", content=thesis(), headers={"X-CSRF-Token": csrf,
                                                          "X-Ruleset": "example"})
    assert res.status_code == 429
    assert "Günlük" in res.json()["error"]


@pytest.mark.xfail(strict=True, reason=(
    "Günlük sınır silinmemiş işleri sayıyor; öğrenci raporu silip yeniden yükleyerek "
    "sınırı aşabilir. "
    "Öneri: ONERILER Ö5 (sayacı iş kaydından bağımsız tut)."))
def test_daily_job_limit_survives_deleting_reports(client: TestClient, mailer: ConsoleMailer,
                                                   settings: Settings) -> None:
    csrf = login(client, mailer)
    db = client.app.state.db  # type: ignore[attr-defined]
    for i in range(settings.max_daily_jobs):
        db.add_job(f"gunluk-is-{i:010d}", EMAIL, "example")
        db.finish_job(f"gunluk-is-{i:010d}", report=None, error_code="INTERNAL")
        client.post(f"/jobs/gunluk-is-{i:010d}/delete", data={"csrf": csrf})
    res = client.post("/jobs", content=thesis(), headers={"X-CSRF-Token": csrf,
                                                          "X-Ruleset": "example"})
    assert res.status_code == 429


@pytest.mark.xfail(strict=True, reason=(
    "Kopya üretimi (output) eşzamanlı iş sınırına ve günlük sınıra tabi değil; her istek ayrı "
    "süreçte (2 GB'a kadar) çalışır. Paralel isteklerle sunucu belleği tüketilebilir. "
    "Öneri: ONERILER Ö6."))
def test_output_respects_concurrency_limit(client: TestClient, mailer: ConsoleMailer,
                                           settings: Settings) -> None:
    csrf = login(client, mailer)
    data = bad_thesis()
    job_id = upload(client, csrf, data)
    wait_done(client, job_id)
    db = client.app.state.db  # type: ignore[attr-defined]
    for i in range(settings.max_active_jobs):
        db.add_job(f"bekleyen-is-{i:08d}", EMAIL, "example")
    assert output(client, csrf, job_id, "fixed", data).status_code == 429


@pytest.mark.xfail(strict=True, reason=(
    "Giriş isteği sınırı yalnızca e-posta başına (saatte 5). Tek istemci izinli alandaki farklı "
    "adreslere sınırsız bağlantı gönderebilir (e-posta bombardımanı, SMTP itibarı). "
    "Öneri: ONERILER Ö7 (IP başına ve genel sınır)."))
def test_login_requests_limited_per_client(client: TestClient, mailer: ConsoleMailer,
                                           settings: Settings) -> None:
    statuses = []
    for i in range(settings.login_requests_per_hour * 6):
        page = client.get("/")
        res = client.post("/login", data={"email": f"kisi{i}@beun.edu.tr",
                                          "csrf": csrf_from(page.text)})
        statuses.append(res.status_code)
    assert len(mailer.sent) <= settings.login_requests_per_hour * 2


@pytest.mark.xfail(strict=True, reason=(
    "Saklama süresi dolan rapor, temizlik görevi (10 dakikada bir) çalışana kadar açılabiliyor. "
    "Gizlilik sözü '24 saat sonra silinir'. Öneri: ONERILER Ö8 (okurken yaşı denetle)."))
def test_expired_report_is_not_served_before_purge(client: TestClient,
                                                   mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, thesis())
    wait_done(client, job_id)
    db = client.app.state.db  # type: ignore[attr-defined]
    db.execute("UPDATE jobs SET created_at = created_at - 90000 WHERE id=?", (job_id,))
    assert client.get(f"/jobs/{job_id}/report.json").status_code == 404


def test_copy_of_failed_job_is_refused(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, b"word degil")
    wait_done(client, job_id)
    assert output(client, csrf, job_id, "fixed", b"word degil").status_code == 409
    res = client.post(f"/jobs/{job_id}/recheck", content=b"word degil",
                      headers={"X-CSRF-Token": csrf})
    assert res.status_code == 409


def test_unknown_output_kind_is_404(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, thesis())
    wait_done(client, job_id)
    # İstemci yolu normalleştirir (/jobs/etc/...): hiçbir uç noktaya düşmez.
    assert output(client, csrf, job_id, "../../etc", thesis()).status_code in (404, 405)
    assert output(client, csrf, job_id, "original", thesis()).status_code == 404
