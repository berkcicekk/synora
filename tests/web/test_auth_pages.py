"""Giriş ve kayıt sayfaları (A9 /giris, /kayit, /aydinlatma; A11 bölünmüş panel düzeni).

Giriş parolasız: iki sayfa da e-postaya tek kullanımlık bağlantı gönderir. Kayıt ayrıca aydınlatma
metni onayı ister; onay yalnızca bağlantı açılıp e-posta doğrulandığında kaydedilir.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from test_web import csrf_from, login

from synora.web.app import TERMS_VERSION
from synora.web.db import Database
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

EMAIL = "ogrenci@beun.edu.tr"


def register(client: TestClient, email: str = EMAIL, kvkk: bool = True) -> int:
    page = client.get("/kayit")
    data = {"email": email, "csrf": csrf_from(page.text)}
    if kvkk:
        data["kvkk"] = "1"
    return client.post("/kayit", data=data).status_code


def confirm(client: TestClient, mailer: ConsoleMailer) -> None:
    token = mailer.sent[-1][1].split("token=")[1]
    csrf = csrf_from(client.get(f"/auth?token={token}").text)
    res = client.post("/auth", data={"token": token, "csrf": csrf}, follow_redirects=False)
    assert res.status_code == 303


def consent(client: TestClient, email: str = EMAIL) -> tuple[str, float] | None:
    db: Database = client.app.state.db  # type: ignore[attr-defined]
    return db.user_consent(email)


# --- Sayfalar ---------------------------------------------------------------------------------


def test_login_page_split_layout(client: TestClient) -> None:
    res = client.get("/giris")
    assert res.status_code == 200
    html = res.text
    assert '<div class="auth-shell">' in html
    assert 'class="auth-art"' in html and "auth-mark" in html  # solda büyük amblem
    form = html[html.index('<form method="post" action="/login"'):]
    form = form[:form.index("</form>")]
    assert 'name="csrf"' in form and 'type="email"' in form and 'autocomplete="email"' in form
    assert 'name="kvkk"' not in form
    assert re.search(r'<a href="/giris"[^>]*aria-current="page">Giriş yap</a>', html)
    assert 'href="/kayit"' in html
    assert "<title>Giriş yap · Synora</title>" in html
    assert 'class="site-nav"' not in html  # odaklı sayfa: üst menü ve altbilgi yok


def test_register_page_requires_consent_checkbox(client: TestClient) -> None:
    html = client.get("/kayit").text
    assert '<div class="auth-shell">' in html
    form = html[html.index('<form method="post" action="/kayit"'):]
    form = form[:form.index("</form>")]
    assert re.search(r'<input id="kvkk" name="kvkk" type="checkbox" value="1" required', form)
    assert 'for="kvkk"' in form or '<label class="check"' in form
    assert 'href="/aydinlatma"' in form
    assert re.search(r'<a href="/kayit"[^>]*aria-current="page">Kayıt ol</a>', html)
    assert "<title>Kayıt ol · Synora</title>" in html


def test_auth_pages_set_pre_login_csrf_cookie(client: TestClient) -> None:
    for path in ("/giris", "/kayit"):
        res = client.get(path)
        assert "synora_pre=" in res.headers.get("set-cookie", ""), path


def test_logged_in_user_is_sent_home(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    for path in ("/giris", "/kayit"):
        res = client.get(path, follow_redirects=False)
        assert res.status_code == 303 and res.headers["location"] == "/", path


def test_landing_links_to_auth_pages_instead_of_form(client: TestClient) -> None:
    html = client.get("/").text
    assert 'action="/login"' not in html
    assert 'href="/giris"' in html and 'href="/kayit"' in html
    assert 'id="giris"' in html  # kahramandaki "Başlayın" çapası hâlâ bir yere iner


def test_privacy_notice_page_is_marked_draft(client: TestClient, settings: Settings) -> None:
    res = client.get("/aydinlatma")
    assert res.status_code == 200
    assert "Taslak" in res.text
    assert f"{int(settings.retention_hours)} saat" in res.text


def test_link_sent_and_confirm_pages_use_auth_layout(client: TestClient,
                                                     mailer: ConsoleMailer) -> None:
    assert register(client) == 200
    token = mailer.sent[-1][1].split("token=")[1]
    for html in (client.get(f"/auth?token={token}").text, client.get("/auth?token=yok").text):
        assert '<div class="auth-shell">' in html
    page = client.get("/kayit")
    sent = client.post("/kayit", data={"email": EMAIL, "csrf": csrf_from(page.text), "kvkk": "1"})
    assert '<div class="auth-shell">' in sent.text and "E-postanızı kontrol edin" in sent.text


# --- Kayıt akışı ------------------------------------------------------------------------------


def test_register_without_consent_is_rejected(client: TestClient, mailer: ConsoleMailer) -> None:
    page = client.get("/kayit")
    res = client.post("/kayit", data={"email": EMAIL, "csrf": csrf_from(page.text)})
    assert res.status_code == 400
    assert "aydınlatma metnini onaylayın" in res.text
    assert 'value="ogrenci@beun.edu.tr"' in res.text  # yazdığı adres kaybolmaz
    assert mailer.sent == []


def test_register_records_consent_only_after_email_is_verified(
        client: TestClient, mailer: ConsoleMailer) -> None:
    assert register(client) == 200
    assert len(mailer.sent) == 1
    assert consent(client) is None  # bağlantı açılmadan kimse adına onay yazılmaz
    confirm(client, mailer)
    found = consent(client)
    assert found is not None and found[0] == TERMS_VERSION
    assert "Tezinizi yükleyin" in client.get("/").text


def test_plain_login_does_not_record_consent(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    assert consent(client) is None


def test_register_keeps_login_protections(client: TestClient, mailer: ConsoleMailer,
                                          settings: Settings) -> None:
    page = client.get("/kayit")
    assert client.post("/kayit", data={"email": EMAIL, "csrf": "yanlis",
                                       "kvkk": "1"}).status_code == 403
    res = client.post("/kayit", data={"email": "biri@gmail.com", "csrf": csrf_from(page.text),
                                      "kvkk": "1"})
    assert res.status_code == 400 and "üniversite e-posta" in res.text
    assert mailer.sent == []
    # Giriş ve kayıt aynı saatlik sınırı paylaşır.
    for _ in range(settings.login_requests_per_hour):
        assert register(client) == 200
    page = client.get("/giris")
    res = client.post("/login", data={"email": EMAIL, "csrf": csrf_from(page.text)})
    assert res.status_code == 400 and "Çok fazla" in res.text


def test_login_errors_render_login_page(client: TestClient) -> None:
    page = client.get("/giris")
    res = client.post("/login", data={"email": "adres-degil", "csrf": csrf_from(page.text)})
    assert res.status_code == 400
    assert '<div class="auth-shell">' in res.text and 'action="/login"' in res.text
    assert 'role="alert"' in res.text


def test_existing_database_gains_consent_columns(tmp_path: Path) -> None:
    path = tmp_path / "eski.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE login_tokens (token_hash TEXT PRIMARY KEY, email TEXT NOT NULL,
            created_at REAL NOT NULL, expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
        INSERT INTO login_tokens VALUES ('h', 'a@beun.edu.tr', 0, 9e12, 0);
    """)
    conn.close()
    db = Database(path)
    assert db.consume_login_token("h") == "a@beun.edu.tr"
    assert db.user_consent("a@beun.edu.tr") is None
    db.add_login_token("h2", "a@beun.edu.tr", 60, consent="v1")
    assert db.consume_login_token("h2") == "a@beun.edu.tr"
    found = db.user_consent("a@beun.edu.tr")
    assert found is not None and found[0] == "v1"
