"""22 Ekim güvenlik taraması paketi (A9, onay 2026-10-23).

O3 demo kipinde rapor oturuma bağlı · Y2 aynı anda okunan yükleme gövdesi sınırı · Y1 istemci
IP başlığı ayardan · O1 hız sınırlayıcı büyümez · O2 öneri kutusu tavanı · D1 para_id biçimi ·
kopya/yeniden denetimde Content-Length ön kontrolü · indirme adları · security.txt ·
Türkçe klavyeyle yazılmış adresler.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_direct_auth import login as direct_login
from test_direct_auth import register
from test_web import bad_thesis, csrf_from, login, output, upload, wait_done

from synora.web.app import SESSION_COOKIE, RateLimiter, create_app
from synora.web.db import SUGGESTION_KEEP_DAYS, SUGGESTION_KEEP_ROWS, Database
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
DEMO_EMAIL = "ogrenci@beun.edu.tr"


def upload_csrf(client: TestClient) -> str:
    return csrf_from(client.get("/yukle").text.split('id="upload"')[1])


def ready_job(client: TestClient, mailer: ConsoleMailer) -> tuple[str, str]:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, bad_thesis())
    assert wait_done(client, job_id) == "done"
    return job_id, csrf


# --- ASGI düzeyinde istek: gövde okumaları sayılır, gövde bekletilebilir ----------------------


async def asgi_post(app: Any, path: str, headers: dict[str, str], body: bytes,
                    hold: asyncio.Event | None = None,
                    started: asyncio.Event | None = None) -> tuple[int, int]:
    """(durum kodu, receive çağrısı sayısı). hold verilirse gövdenin ilk parçası gelir,
    kalanı hold açılana kadar bekler (yavaş yükleme)."""
    reads = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal reads
        reads += 1
        if hold is None:
            return {"type": "http.request", "body": body, "more_body": False}
        if reads == 1:
            if started is not None:
                started.set()
            return {"type": "http.request", "body": body[:1024], "more_body": True}
        if reads == 2:
            await hold.wait()
            return {"type": "http.request", "body": body[1024:], "more_body": False}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
        "headers": [(b"host", b"testserver"), *raw],
    }
    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], reads


def session_headers(client: TestClient, csrf: str, length: int) -> dict[str, str]:
    return {"cookie": f"{SESSION_COOKIE}={client.cookies.get(SESSION_COOKIE)}",
            "x-csrf-token": csrf, "x-ruleset": "example",
            "content-type": "application/octet-stream", "content-length": str(length)}


# --- O3: demo kipinde rapor yalnızca onu başlatan oturumda -----------------------------------


@pytest.fixture
def demo_settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "d.db", rulesets_dir=ROOT / "rulesets", base_url="http://testserver",
        allowed_domains=(".edu.tr",), dev=True, isolate_jobs=False, workers=1,
        email_verification=False,
    )


@pytest.fixture
def demo_pair(demo_settings: Settings,
              mailer: ConsoleMailer) -> Iterator[tuple[TestClient, TestClient]]:
    app = create_app(demo_settings, mailer)
    with TestClient(app) as owner, TestClient(app) as other:
        yield owner, other


def test_demo_report_is_bound_to_the_session_that_started_it(
        demo_pair: tuple[TestClient, TestClient]) -> None:
    owner, other = demo_pair
    assert register(owner, email=DEMO_EMAIL).status_code == 303
    csrf = upload_csrf(owner)
    job_id = upload(owner, csrf, bad_thesis())
    assert wait_done(owner, job_id) == "done"
    assert job_id in owner.get("/").text
    assert owner.get(f"/jobs/{job_id}").status_code == 200

    # Aynı adresle (doğrulamasız) giren başkası ne listede görür ne de açabilir.
    assert direct_login(other, email=DEMO_EMAIL).status_code == 303
    panel = other.get("/")
    assert "Son denetimler" in panel.text
    assert job_id not in panel.text
    assert other.get(f"/jobs/{job_id}").status_code == 404
    assert other.get(f"/jobs/{job_id}/status").status_code == 404
    assert other.get(f"/jobs/{job_id}/report.json").status_code == 404
    other_csrf = upload_csrf(other)
    res = other.post(f"/jobs/{job_id}/delete", data={"csrf": other_csrf}, follow_redirects=False)
    assert res.status_code == 404
    assert owner.get(f"/jobs/{job_id}").status_code == 200  # silinmedi


def test_demo_panel_says_history_is_per_session(
        demo_pair: tuple[TestClient, TestClient]) -> None:
    owner, _ = demo_pair
    register(owner, email=DEMO_EMAIL)
    assert "yalnızca bu oturumda" in owner.get("/").text


def test_verified_mode_keeps_history_across_sessions(settings: Settings,
                                                     mailer: ConsoleMailer) -> None:
    """E-posta doğrulanınca adres sahibi kanıtlanmış olur: iki cihazda da geçmiş görünür."""
    app = create_app(settings, mailer)
    with TestClient(app) as a, TestClient(app) as b:
        job_id, _ = ready_job(a, mailer)
        login(b, mailer)
        assert job_id in b.get("/").text
        assert b.get(f"/jobs/{job_id}").status_code == 200
        assert "yalnızca bu oturumda" not in b.get("/").text


# --- Y2: aynı anda okunan yükleme gövdesi sayısı sınırlı -------------------------------------


@pytest.mark.parametrize(("in_flight", "active", "expected"), [(1, 10, 503), (10, 1, 429)])
def test_parallel_uploads_are_refused_before_reading_body(
        settings: Settings, mailer: ConsoleMailer, in_flight: int, active: int,
        expected: int) -> None:
    s = replace(settings, max_uploads_in_flight=in_flight, max_active_jobs=active)
    app = create_app(s, mailer)
    with TestClient(app) as client:
        csrf = login(client, mailer)
        body = bad_thesis()
        headers = session_headers(client, csrf, len(body))

        async def scenario() -> tuple[int, int, int]:
            hold, started = asyncio.Event(), asyncio.Event()
            first = asyncio.create_task(asgi_post(app, "/jobs", headers, body, hold, started))
            await asyncio.wait_for(started.wait(), 10)
            status2, reads2 = await asgi_post(app, "/jobs", headers, body)
            hold.set()
            status1, _ = await asyncio.wait_for(first, 30)
            return status1, status2, reads2

        status1, status2, reads2 = asyncio.run(scenario())
        assert status1 == 202
        assert status2 == expected
        assert reads2 == 0, "ikinci yüklemenin gövdesi okundu"


def test_upload_slot_is_released_after_a_rejected_upload(settings: Settings,
                                                         mailer: ConsoleMailer) -> None:
    data = bad_thesis()
    s = replace(settings, max_uploads_in_flight=1, max_upload_bytes=len(data) + 10)
    with TestClient(create_app(s, mailer)) as client:
        csrf = login(client, mailer)
        too_big = client.post("/jobs", content=iter([data, b"x" * 100]), headers={
            "X-CSRF-Token": csrf, "X-Ruleset": "example",
            "Content-Type": "application/octet-stream"})
        assert too_big.status_code == 413
        job_id = upload(client, csrf, data)
        assert wait_done(client, job_id) == "done"


def test_recheck_counts_as_upload_in_flight(settings: Settings, mailer: ConsoleMailer) -> None:
    with TestClient(create_app(settings, mailer)) as client:
        job_id, csrf = ready_job(client, mailer)
        cookies = dict(client.cookies)
    # Aynı veritabanı, yükleme yeri olmayan sunucu: yeniden denetim de yer ister.
    busy = replace(settings, max_uploads_in_flight=0)
    with TestClient(create_app(busy, mailer), cookies=cookies) as client:
        res = client.post(f"/jobs/{job_id}/recheck", content=bad_thesis(), headers={
            "X-CSRF-Token": csrf, "Content-Type": "application/octet-stream"})
        assert res.status_code == 503
        assert "yoğun" in res.json()["error"]
        res = client.post("/jobs", content=bad_thesis(), headers={
            "X-CSRF-Token": csrf, "X-Ruleset": "example",
            "Content-Type": "application/octet-stream"})
        assert res.status_code == 503


# --- Kopya / yeniden denetim: büyük gövde okunmadan reddedilir --------------------------------


@pytest.mark.parametrize("path", ["output/fixed", "recheck"])
def test_same_file_checks_declared_length_before_reading(settings: Settings,
                                                         mailer: ConsoleMailer,
                                                         path: str) -> None:
    app = create_app(settings, mailer)
    with TestClient(app) as client:
        job_id, csrf = ready_job(client, mailer)
        headers = session_headers(client, csrf, settings.max_upload_bytes + 1)
        status, reads = asyncio.run(asgi_post(app, f"/jobs/{job_id}/{path}", headers, b"PK"))
        assert status == 413
        assert reads == 0


def test_report_page_tells_the_browser_the_size_limit(client: TestClient,
                                                      mailer: ConsoleMailer,
                                                      settings: Settings) -> None:
    job_id, _ = ready_job(client, mailer)
    page = client.get(f"/jobs/{job_id}").text
    toolbar = page.split('id="outputs"')[1].split(">")[0]
    assert f'data-max="{settings.max_upload_bytes}"' in toolbar


# --- Y1: istemci IP'si hangi başlıktan okunur -------------------------------------------------


def _login_posts(client: TestClient, headers: list[dict[str, str]]) -> list[int]:
    out = []
    for i, h in enumerate(headers):
        page = client.get("/giris")
        res = client.post("/login", data={"email": f"kisi{i}@beun.edu.tr",
                                          "csrf": csrf_from(page.text)}, headers=h)
        out.append(res.status_code)
    return out


def test_configured_ip_header_ignores_spoofed_cf_header(settings: Settings,
                                                        mailer: ConsoleMailer) -> None:
    s = replace(settings, client_ip_header="x-real-ip", login_requests_per_ip_hour=2)
    with TestClient(create_app(s, mailer)) as client:
        spoofed = [{"X-Real-IP": "203.0.113.7", "CF-Connecting-IP": f"198.51.100.{i}"}
                   for i in range(3)]
        assert _login_posts(client, spoofed) == [200, 200, 429]


def test_default_ip_header_is_cloudflare(settings: Settings, mailer: ConsoleMailer) -> None:
    assert Settings().client_ip_header == "cf-connecting-ip"
    s = replace(settings, login_requests_per_ip_hour=2)
    with TestClient(create_app(s, mailer)) as client:
        distinct = [{"CF-Connecting-IP": f"198.51.100.{i}"} for i in range(3)]
        assert _login_posts(client, distinct) == [200, 200, 200]


def test_empty_ip_header_uses_socket_address(settings: Settings, mailer: ConsoleMailer) -> None:
    s = replace(settings, client_ip_header="", login_requests_per_ip_hour=2)
    with TestClient(create_app(s, mailer)) as client:
        distinct = [{"CF-Connecting-IP": f"198.51.100.{i}"} for i in range(3)]
        assert _login_posts(client, distinct) == [200, 200, 429]


def test_ip_header_from_env_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNORA_CLIENT_IP_HEADER", " X-Real-IP ")
    assert Settings.from_env().client_ip_header == "x-real-ip"
    bad = Settings(base_url="https://x.example", email_verification=False,
                   allowed_domains=(".edu.tr",), client_ip_header="x real ip")
    assert any("SYNORA_CLIENT_IP_HEADER" in p for p in bad.problems())


# --- O1: hız sınırlayıcı belleği reddederken büyümez ------------------------------------------


def test_rate_limiter_does_not_store_rejected_new_clients() -> None:
    limiter = RateLimiter(per_key_hour=5, per_minute=1)
    assert limiter.allow("ilk", now=1000.0)
    for i in range(5000):  # site geneli sınır dolu: her yeni istemci reddedilir
        assert not limiter.allow(f"k{i}", now=1000.0 + i / 1000)
    assert len(limiter) == 1


def test_rate_limiter_drops_stale_clients() -> None:
    limiter = RateLimiter(per_key_hour=5, per_minute=10**6)
    for i in range(1500):
        limiter.allow(f"k{i}", now=0.0)
    assert limiter.allow("yeni", now=4000.0)
    assert len(limiter) == 1


def test_rate_limiter_still_limits_per_client() -> None:
    limiter = RateLimiter(per_key_hour=2, per_minute=100)
    assert [limiter.allow("a", now=t) for t in (0.0, 1.0, 2.0)] == [True, True, False]
    assert limiter.allow("b", now=3.0)
    assert limiter.allow("a", now=3700.0)  # pencere geçti


# --- O2: öneri kutusu tavanı ve saklama süresi ------------------------------------------------


def test_suggestions_are_capped_and_expire(tmp_path: Path) -> None:
    db = Database(tmp_path / "s.db")
    old = time.time() - (SUGGESTION_KEEP_DAYS + 1) * 86400
    db.execute("INSERT INTO suggestions (message, email, page, created_at) "
               "VALUES ('eski', '', '', ?)", (old,))
    for i in range(SUGGESTION_KEEP_ROWS + 50):
        db.add_suggestion(f"m{i}", "", "")
    db.purge(86400)
    rows = db.suggestions(limit=10**6)
    assert len(rows) == SUGGESTION_KEEP_ROWS
    assert all(r[3] != "eski" for r in rows)
    assert rows[0][3] == f"m{SUGGESTION_KEEP_ROWS + 49}"  # en yeniler kalır


# --- D1: para_id biçimi -----------------------------------------------------------------------


@pytest.mark.parametrize(("para_id", "status"), [
    ("", 200), ("p12", 200), ("1A2B3C4D", 200),
    ("<b>x</b>", 400), ("p12 x", 400), ("../etc", 400), ("123456789", 400), ("zz", 400),
])
def test_feedback_para_id_format(client: TestClient, mailer: ConsoleMailer,
                                 para_id: str, status: int) -> None:
    job_id, csrf = ready_job(client, mailer)
    res = client.post(f"/jobs/{job_id}/feedback", headers={"X-CSRF-Token": csrf}, data={
        "rule_id": "body.line_spacing", "verdict": "wrong", "para_id": para_id})
    assert res.status_code == status


# --- İndirme adları ve security.txt -----------------------------------------------------------


def test_download_names_use_payper(client: TestClient, mailer: ConsoleMailer) -> None:
    job_id, csrf = ready_job(client, mailer)
    report = client.get(f"/jobs/{job_id}/report.json")
    assert report.headers["content-disposition"] == 'attachment; filename="payper-rapor.json"'
    data = bad_thesis()
    for kind, name in (("fixed", "payper-duzeltilmis.docx"),
                       ("annotated", "payper-yorumlu.docx")):
        res = output(client, csrf, job_id, kind, data)
        assert res.status_code == 200
        assert res.headers["content-disposition"] == f'attachment; filename="{name}"'


def test_security_txt_points_to_private_advisories(client: TestClient) -> None:
    body = client.get("/.well-known/security.txt").text
    assert "Contact: https://github.com/berkcicekk/synora/security/advisories/new" in body


# --- Türkçe klavyeyle yazılmış adresler -------------------------------------------------------


@pytest.mark.parametrize(("typed", "target"), [
    ("/yonet%C4%B1m", "/yonetim"),
    ("/g%C4%B1r%C4%B1s", "/giris"),
    ("/G%C4%B0R%C4%B0%C5%9E", "/giris"),
    ("/aydinlatma%C4%B1", None),
    ("/%2Fev%C4%B1l.example", None),
])
def test_turkish_keyboard_paths_redirect_to_known_pages(client: TestClient, typed: str,
                                                        target: str | None) -> None:
    res = client.get(typed, follow_redirects=False)
    if target is None:
        assert res.status_code == 404
    else:
        assert res.status_code == 308
        assert res.headers["location"] == target
