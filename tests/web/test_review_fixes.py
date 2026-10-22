"""Gece gözden geçirmesinde bulunanlar: günlük sınır yalnızca yeni yüklemede, onayı e-posta sahibi
kendisi verir, 500 sayfası güvenlik başlıklı ve ayrıntısız, 405 Allow başlığını korur."""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_auth_pages import consent, register
from test_web import bad_thesis, csrf_from, login, output, recheck, upload, wait_done

from synora.web.app import create_app
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings


def test_daily_limit_does_not_block_existing_report(settings: Settings,
                                                    mailer: ConsoleMailer) -> None:
    with TestClient(create_app(replace(settings, max_daily_jobs=1), mailer)) as client:
        csrf = login(client, mailer)
        data = bad_thesis()
        job_id = upload(client, csrf, data)
        wait_done(client, job_id)
        assert output(client, csrf, job_id, "fixed", data).status_code == 200
        assert recheck(client, csrf, job_id, data).status_code == 202
        wait_done(client, job_id)
        res = client.post("/jobs", content=data, headers={
            "X-CSRF-Token": csrf, "X-Ruleset": "example",
            "Content-Type": "application/octet-stream"})
        assert res.status_code == 429  # yeni yükleme sınırı aşar


# --- Onayı e-posta sahibi verir --------------------------------------------------------------


def _token(mailer: ConsoleMailer) -> str:
    return mailer.sent[-1][1].split("token=")[1]


def test_register_link_asks_owner_to_confirm_consent(client: TestClient,
                                                     mailer: ConsoleMailer) -> None:
    # Başkası bu adresle kayıt formunu doldurmuş olabilir: onay kutusunu adres sahibi işaretler.
    assert register(client) == 200
    token = _token(mailer)
    page = client.get(f"/auth?token={token}").text
    assert '<input id="kvkk" name="kvkk" type="checkbox" value="1" required' in page
    res = client.post("/auth", data={"token": token, "csrf": csrf_from(page)},
                      follow_redirects=False)
    assert res.status_code == 400 and "aydınlatma metnini onaylayın" in res.text
    assert consent(client) is None
    assert "Son denetimler" not in client.get("/").text  # oturum açılmadı
    res = client.post("/auth", data={"token": token, "csrf": csrf_from(res.text), "kvkk": "1"},
                      follow_redirects=False)
    assert res.status_code == 303
    assert consent(client) is not None


def test_plain_login_link_has_no_consent_box(client: TestClient, mailer: ConsoleMailer) -> None:
    page = client.get("/giris")
    client.post("/login", data={"email": "ogrenci@beun.edu.tr", "csrf": csrf_from(page.text)})
    html = client.get(f"/auth?token={_token(mailer)}").text
    assert 'name="kvkk"' not in html


# --- Hata yanıtları ---------------------------------------------------------------------------


@pytest.fixture
def boom_client(settings: Settings, mailer: ConsoleMailer) -> TestClient:
    app = create_app(settings, mailer)

    @app.get("/patlat")
    def boom() -> None:
        raise RuntimeError("tez cümlesi burada")

    return TestClient(app)  # raise_server_exceptions=True: hata yeniden fırlatılırsa test patlar


def test_500_page_has_security_headers_and_is_not_reraised(
        boom_client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with boom_client as c, caplog.at_level(logging.DEBUG):
        res = c.get("/patlat")
    assert res.status_code == 500
    assert "default-src 'self'" in res.headers["content-security-policy"]
    assert res.headers["cache-control"] == "no-store"
    assert "tez cümlesi" not in res.text
    assert not any("tez cümlesi" in r.getMessage() or (r.exc_info and "tez cümlesi" in
                   str(r.exc_info[1])) for r in caplog.records)


def test_405_keeps_allow_header(client: TestClient) -> None:
    res = client.post("/fiyatlandirma")
    assert res.status_code == 405
    assert "GET" in res.headers.get("allow", "")
