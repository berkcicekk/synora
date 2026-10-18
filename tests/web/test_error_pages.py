"""Hata yanıtları (ONERILER Ö3): bilinmeyen adres ve yanlış yöntem HTML sayfası, beklenmeyen hata
için 500 sayfası, arayüze giden JSON hataları Türkçe, hata sayfası oturumu bilir."""

from __future__ import annotations

from fastapi.testclient import TestClient
from test_web import csrf_from, login

from synora.web.app import create_app
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings


def test_wrong_method_shows_friendly_page(client: TestClient) -> None:
    res = client.post("/fiyatlandirma")
    assert res.status_code == 405
    assert "text/html" in res.headers["content-type"]
    assert "<h1" in res.text


def test_error_page_knows_the_logged_in_user(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    html = client.get("/boyle-bir-sayfa-yok").text
    assert "ogrenci@beun.edu.tr" in html and 'action="/logout"' in html


def test_json_errors_are_turkish(client: TestClient, mailer: ConsoleMailer) -> None:
    res = client.post("/jobs", content=b"x", headers={"X-Ruleset": "example"})
    assert res.status_code == 401
    assert res.json()["error"].startswith("Oturumunuz sona erdi")
    csrf = login(client, mailer)
    res = client.post("/jobs/aaaaaaaaaaaaaaaaaaaa/recheck", content=b"x",
                      headers={"X-CSRF-Token": csrf})
    assert res.status_code == 404
    assert res.json()["error"] == "Denetim bulunamadı ya da süresi doldu."
    res = client.post("/jobs", content=b"x", headers={"X-CSRF-Token": "yanlis",
                                                      "X-Ruleset": "example"})
    assert res.status_code == 403 and "Sayfayı yenileyip" in res.json()["error"]


def test_unexpected_error_shows_500_page(settings: Settings, mailer: ConsoleMailer) -> None:
    app = create_app(settings, mailer)

    @app.get("/patlat")
    def boom() -> None:
        raise RuntimeError("iç ayrıntı")

    with TestClient(app, raise_server_exceptions=False) as client:
        res = client.get("/patlat")
    assert res.status_code == 500
    assert "text/html" in res.headers["content-type"]
    assert "Beklenmeyen bir hata" in res.text
    assert "iç ayrıntı" not in res.text


def test_expired_login_form_keeps_email(client: TestClient, mailer: ConsoleMailer) -> None:
    client.get("/giris")
    res = client.post("/login", data={"email": "ogrenci@beun.edu.tr", "csrf": "eski"})
    assert res.status_code == 403
    assert "Sayfanın süresi doldu" in res.text
    assert 'value="ogrenci@beun.edu.tr"' in res.text
    assert mailer.sent == []
    # Yeni formla hemen gönderilebilir.
    res = client.post("/login", data={"email": "ogrenci@beun.edu.tr",
                                      "csrf": csrf_from(res.text)})
    assert res.status_code == 200 and len(mailer.sent) == 1


def test_register_domain_error_wording(client: TestClient) -> None:
    page = client.get("/kayit")
    res = client.post("/kayit", data={"email": "biri@gmail.com", "csrf": csrf_from(page.text),
                                      "kvkk": "1"})
    assert "giriş yapılabilir" not in res.text and "kullanılabilir" in res.text
