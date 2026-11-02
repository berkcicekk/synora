"""Yönetim paneli: ayrı sayfalar (sol menü), hesap arama/sayfalama, hesap ekleme ve askıya alma."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_admin_access import AUD, TEAM, jwk, mint
from test_web import csrf_from, login

from synora.web import access as access_module
from synora.web.app import ADMIN_PAGE_SIZE, TERMS_VERSION, create_app
from synora.web.db import Database
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ADMIN = "yonetici@beun.edu.tr"
STUDENT = "ogrenci@beun.edu.tr"
KEY = "dogru-anahtar-0123456789abcdef"
ACTOR = hashlib.sha256(ADMIN.encode()).hexdigest()[:16]
PAGES = ["/yonetim", "/yonetim/hesaplar", "/yonetim/oneriler", "/yonetim/kullanim",
         "/yonetim/sistem", "/yonetim/kayit"]


@pytest.fixture
def admin_settings(settings: Settings) -> Settings:
    return replace(settings, admin_emails=(ADMIN,),
                   admin_key_sha256=hashlib.sha256(KEY.encode()).hexdigest())


@pytest.fixture
def client_(admin_settings: Settings, mailer: ConsoleMailer) -> Iterator[TestClient]:
    with TestClient(create_app(admin_settings, mailer)) as c:
        yield c


def db_of(client: TestClient) -> Database:
    return client.app.state.db  # type: ignore[attr-defined,no-any-return]


def open_panel(client: TestClient, mailer: ConsoleMailer) -> str:
    csrf = login(client, mailer, ADMIN)
    assert client.post("/yonetim/anahtar", data={"key": KEY, "csrf": csrf},
                       follow_redirects=False).status_code == 303
    return csrf


def post(client: TestClient, route: str, **data: Any) -> Any:
    return client.post(route, data=data, follow_redirects=False)


# --- Sayfalar ve sol menü -------------------------------------------------------------------------


@pytest.mark.parametrize("path", PAGES)
def test_every_page_is_404_for_others_and_form_for_locked_admin(
        client_: TestClient, mailer: ConsoleMailer, path: str) -> None:
    assert client_.get(path).status_code == 404
    login(client_, mailer, STUDENT)
    assert client_.get(path).status_code == 404
    locked = TestClient(client_.app)
    login(locked, mailer, ADMIN)
    page = locked.get(path)
    assert page.status_code == 200 and 'name="key"' in page.text
    assert 'class="admin-nav"' not in page.text


@pytest.mark.parametrize("path", PAGES)
def test_every_page_has_side_menu_with_current_item(client_: TestClient, mailer: ConsoleMailer,
                                                    path: str) -> None:
    open_panel(client_, mailer)
    html = client_.get(path).text
    nav = html.split('class="admin-nav"')[1].split("</nav>")[0]
    for target in PAGES:
        assert f'href="{target}"' in nav
    assert len(re.findall(r'aria-current="page"', nav)) == 1
    assert re.search(rf'href="{re.escape(path)}"[^>]*aria-current="page"', nav)
    main = html.split("<main")[1].split("</main>")[0]
    assert "<script" not in main and "style=" not in main  # CSP


@pytest.mark.parametrize("path", PAGES)
def test_access_mode_pages_need_token(settings: Settings, mailer: ConsoleMailer,
                                      monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    monkeypatch.setattr(access_module, "fetch_jwks", lambda team: {"keys": [jwk()]})
    configured = replace(settings, admin_emails=(ADMIN,), access_team_domain=TEAM, access_aud=AUD)
    with TestClient(create_app(configured, mailer)) as c:
        assert c.get(path).status_code == 404
        page = c.get(path, headers={"Cf-Access-Jwt-Assertion": mint()})
        assert page.status_code == 200 and "/cdn-cgi/access/logout" in page.text


def test_sections_live_on_their_own_pages(client_: TestClient, mailer: ConsoleMailer) -> None:
    open_panel(client_, mailer)
    overview = client_.get("/yonetim").text
    assert 'id="n-users"' in overview and 'id="sistem"' not in overview
    assert 'id="sistem"' in client_.get("/yonetim/sistem").text
    assert 'id="kullanim"' in client_.get("/yonetim/kullanim").text
    assert 'id="yanlis-alarm"' in client_.get("/yonetim/kullanim").text
    assert 'id="islem-kaydi"' in client_.get("/yonetim/kayit").text


# --- Hesaplar: arama ve sayfalama -----------------------------------------------------------------


def seed(db: Database, n: int) -> None:
    for i in range(n):
        db.register_user(f"kisi{i:03d}@beun.edu.tr", "test")


def test_accounts_are_paginated(client_: TestClient, mailer: ConsoleMailer) -> None:
    db = db_of(client_)
    seed(db, ADMIN_PAGE_SIZE + 3)
    open_panel(client_, mailer)
    first = client_.get("/yonetim/hesaplar").text
    assert len(re.findall(r'class="admin-email"', first)) == ADMIN_PAGE_SIZE
    assert 'href="/yonetim/hesaplar?sayfa=2"' in first
    second = client_.get("/yonetim/hesaplar", params={"sayfa": 2}).text
    assert len(re.findall(r'class="admin-email"', second)) == 4  # 3 + girişte onay veren yönetici
    assert 'href="/yonetim/hesaplar?sayfa=1"' in second


@pytest.mark.parametrize("value", ["abc", "0", "-3", "99999", "9" * 40])
def test_bad_page_number_is_clamped(client_: TestClient, mailer: ConsoleMailer,
                                    value: str) -> None:
    seed(db_of(client_), 2)
    open_panel(client_, mailer)
    res = client_.get("/yonetim/hesaplar", params={"sayfa": value})
    assert res.status_code == 200 and "kisi000@beun.edu.tr" in res.text


def test_search_is_post_csrf_protected_and_matches_literally(client_: TestClient,
                                                             mailer: ConsoleMailer) -> None:
    db = db_of(client_)
    db.register_user("ali_veli@beun.edu.tr", "test")
    db.register_user("alixveli@beun.edu.tr", "test")
    csrf = open_panel(client_, mailer)
    assert post(client_, "/yonetim/hesaplar/ara", csrf="sahte", q="ali").status_code == 403
    res = post(client_, "/yonetim/hesaplar/ara", csrf=csrf, q="ALI_V")
    assert res.status_code == 200
    assert "ali_veli@beun.edu.tr" in res.text and "alixveli@beun.edu.tr" not in res.text
    assert 'value="ALI_V"' in res.text  # aranan kutuda kalır
    none = post(client_, "/yonetim/hesaplar/ara", csrf=csrf, q="%")
    assert "ali_veli@beun.edu.tr" not in none.text and "Eşleşen hesap yok" in none.text
    assert "ali_veli@beun.edu.tr" in post(client_, "/yonetim/hesaplar/ara", csrf=csrf, q="").text


def test_search_form_keeps_email_out_of_url(client_: TestClient, mailer: ConsoleMailer) -> None:
    open_panel(client_, mailer)
    html = client_.get("/yonetim/hesaplar").text
    assert re.search(r'<form method="post" action="/yonetim/hesaplar/ara"', html)
    # Sonuç sayfalaması arama sonucu için yoktur; adreste e-posta taşınmaz.
    assert "?q=" not in html


def test_search_requires_admin(client_: TestClient, mailer: ConsoleMailer) -> None:
    assert post(client_, "/yonetim/hesaplar/ara", csrf="x", q="a").status_code == 404


# --- Hesap ekleme ---------------------------------------------------------------------------------


def test_add_account_is_pending_and_not_counted(client_: TestClient,
                                                mailer: ConsoleMailer) -> None:
    db = db_of(client_)
    csrf = open_panel(client_, mailer)
    users_before = db.user_count()
    res = post(client_, "/yonetim/hesap/ekle", csrf=csrf, email=f" {STUDENT.upper()} ")
    assert res.status_code == 303 and "durum=eklendi" in res.headers["location"]
    assert "@" not in res.headers["location"]
    assert db.user_consent(STUDENT) is None
    assert db.user_count() == users_before  # ana sayfa sayısına girmez
    assert db.admin_counts(0)["users"] == users_before and db.admin_counts(0)["pending"] == 1
    html = client_.get("/yonetim/hesaplar").text
    assert STUDENT in html and "Onay bekliyor" in html
    assert [r[2] for r in db.admin_log()] == ["account_add"]
    assert STUDENT not in str(db.admin_log())


def test_add_rejects_invalid_foreign_and_existing(client_: TestClient,
                                                  mailer: ConsoleMailer) -> None:
    db = db_of(client_)
    db.register_user(STUDENT, "test")
    csrf = open_panel(client_, mailer)
    for email, status in [("adres-degil", "gecersiz"), ("kisi@gmail.com", "gecersiz"),
                          (STUDENT, "var")]:
        res = post(client_, "/yonetim/hesap/ekle", csrf=csrf, email=email)
        assert f"durum={status}" in res.headers["location"]
    assert db.user_consent(STUDENT) is not None  # var olan onay ezilmez
    assert db.admin_log() == []


def test_registering_pending_account_records_own_consent(tmp_path: Path) -> None:
    db = Database(tmp_path / "d.db")
    assert db.add_pending_user(STUDENT, actor=ACTOR, target="hedef")
    db.register_user(STUDENT, TERMS_VERSION)
    consent = db.user_consent(STUDENT)
    assert consent is not None and consent[0] == TERMS_VERSION
    assert db.user_count() == 1 and not db.add_pending_user(STUDENT, actor=ACTOR, target="hedef")


# --- Askıya alma ----------------------------------------------------------------------------------


def demo_settings(settings: Settings) -> Settings:
    return replace(settings, email_verification=False, admin_emails=(ADMIN,),
                   admin_key_sha256=hashlib.sha256(KEY.encode()).hexdigest())


def demo_form(client: TestClient, path: str, action: str, **extra: str) -> Any:
    page = client.get(path)
    return client.post(action, data={"email": STUDENT, "csrf": csrf_from(page.text), **extra},
                       follow_redirects=False)


def test_suspend_ends_sessions_and_blocks_login_until_activated(
        client_: TestClient, mailer: ConsoleMailer) -> None:
    db = db_of(client_)
    db.register_user(STUDENT, "test")
    student = TestClient(client_.app)
    login(student, mailer, STUDENT)
    assert student.get("/yukle").status_code == 200
    csrf = open_panel(client_, mailer)

    res = post(client_, "/yonetim/hesap/askiya-al", csrf=csrf, email=STUDENT)
    assert res.status_code == 303 and "durum=askida" in res.headers["location"]
    assert "Askıda" in client_.get("/yonetim/hesaplar").text
    assert db.execute("SELECT COUNT(*) FROM sessions WHERE email=?", (STUDENT,)).fetchone()[0] == 0
    assert "Son denetimler" not in student.get("/").text

    blocked = TestClient(client_.app)
    page = blocked.get("/giris")
    sent = len(mailer.sent)
    res = blocked.post("/login", data={"email": STUDENT, "csrf": csrf_from(page.text)})
    assert res.status_code == 200  # dışarıdan normal giriş gibi görünür
    assert len(mailer.sent) == sent  # ama bağlantı gönderilmez

    res = post(client_, "/yonetim/hesap/etkinlestir", csrf=csrf, email=STUDENT)
    assert "durum=etkin" in res.headers["location"]
    login(blocked, mailer, STUDENT)
    assert [r[2] for r in db.admin_log()] == ["account_activate", "account_suspend"]
    assert STUDENT not in str(db.admin_log())


def test_suspension_cancels_login_links_already_sent(client_: TestClient,
                                                     mailer: ConsoleMailer) -> None:
    db = db_of(client_)
    db.register_user(STUDENT, "test")
    student = TestClient(client_.app)
    page = student.get("/giris")
    assert student.post("/login", data={"email": STUDENT,
                                        "csrf": csrf_from(page.text)}).status_code == 200
    token = mailer.sent[-1][1].split("token=")[1]
    csrf = open_panel(client_, mailer)
    post(client_, "/yonetim/hesap/askiya-al", csrf=csrf, email=STUDENT)
    assert not db.login_token_valid(hashlib.sha256(token.encode()).hexdigest())
    confirm = student.get(f"/auth?token={token}")
    assert 'name="token"' not in confirm.text  # ölü bağlantı onay formu göstermez
    assert "Son denetimler" not in student.get("/").text


def test_session_row_is_useless_while_suspended(tmp_path: Path) -> None:
    db = Database(tmp_path / "d.db")
    db.register_user(STUDENT, "test")
    assert db.set_suspended(STUDENT, True, actor=ACTOR, target="hedef")
    db.add_session("yarista-acilan", STUDENT, "csrf", 3600)  # askıyla yarışan giriş
    assert db.get_session("yarista-acilan") is None
    db.add_session("kayitsiz", "duz-giris@beun.edu.tr", "csrf", 3600)
    assert db.get_session("kayitsiz") is not None  # hesapsız düz giriş etkilenmez


def test_demo_mode_cannot_lift_suspension_by_registering(settings: Settings,
                                                         mailer: ConsoleMailer) -> None:
    with TestClient(create_app(demo_settings(settings), mailer)) as c:
        db = db_of(c)
        db.register_user(STUDENT, "test")
        db.set_suspended(STUDENT, True, actor=ACTOR, target="hedef")
        for path, action, extra in [("/kayit", "/kayit", {"kvkk": "1"}),
                                    ("/giris", "/login", {})]:
            res = demo_form(c, path, action, **extra)
            assert res.status_code == 400 and "giriş şu anda kapalı" in res.text
        assert db.is_suspended(STUDENT)
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_suspend_refuses_admin_unknown_and_repeat(client_: TestClient,
                                                  mailer: ConsoleMailer) -> None:
    db = db_of(client_)
    db.register_user(ADMIN, "test")
    db.register_user(STUDENT, "test")
    csrf = open_panel(client_, mailer)
    res = post(client_, "/yonetim/hesap/askiya-al", csrf=csrf, email=ADMIN)
    assert "durum=yonetici" in res.headers["location"] and not db.is_suspended(ADMIN)
    res = post(client_, "/yonetim/hesap/askiya-al", csrf=csrf, email="yok@beun.edu.tr")
    assert "durum=yok" in res.headers["location"]
    res = post(client_, "/yonetim/hesap/etkinlestir", csrf=csrf, email=STUDENT)  # zaten etkin
    assert "durum=yok" in res.headers["location"]
    assert db.admin_log() == []


@pytest.mark.parametrize("route", ["/yonetim/hesap/ekle", "/yonetim/hesap/askiya-al",
                                   "/yonetim/hesap/etkinlestir", "/yonetim/oneri/okunmadi"])
def test_new_actions_require_admin_and_csrf(client_: TestClient, mailer: ConsoleMailer,
                                            route: str) -> None:
    db = db_of(client_)
    db.register_user(STUDENT, "test")
    assert post(client_, route, csrf="x", email=STUDENT, id="1").status_code == 404
    open_panel(client_, mailer)
    assert post(client_, route, csrf="sahte", email=STUDENT, id="1").status_code == 403
    assert client_.get(route).status_code == 405
    assert not db.is_suspended(STUDENT) and db.admin_log() == []


def test_old_database_gains_suspended_column(tmp_path: Path) -> None:
    path = tmp_path / "eski.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (email TEXT PRIMARY KEY, created_at REAL NOT NULL, "
                 "consent_version TEXT, consent_at REAL)")
    conn.execute(f"INSERT INTO users VALUES ('{STUDENT}', 1.0, 'v', 1.0)")
    conn.commit()
    conn.close()
    assert not Database(path).is_suspended(STUDENT)


# --- Öneriler -------------------------------------------------------------------------------------


def test_suggestion_unread_toggle_and_filter(client_: TestClient, mailer: ConsoleMailer) -> None:
    db = db_of(client_)
    db.add_suggestion("birinci mesaj", "", "/")
    db.add_suggestion("ikinci mesaj", "", "/")
    csrf = open_panel(client_, mailer)
    post(client_, "/yonetim/oneri/okundu", csrf=csrf, id="1")
    only_new = client_.get("/yonetim/oneriler", params={"filtre": "okunmamis"}).text
    assert "ikinci mesaj" in only_new and "birinci mesaj" not in only_new
    everything = client_.get("/yonetim/oneriler").text
    assert "ikinci mesaj" in everything and "birinci mesaj" in everything

    res = post(client_, "/yonetim/oneri/okunmadi", csrf=csrf, id="1")
    assert "durum=okunmadi" in res.headers["location"]
    res = post(client_, "/yonetim/oneri/okunmadi", csrf=csrf, id="1")  # zaten okunmamış
    assert "durum=yok" in res.headers["location"]
    assert "birinci mesaj" in client_.get("/yonetim/oneriler",
                                          params={"filtre": "okunmamis"}).text
    assert [r[2] for r in db.admin_log()] == ["suggestion_unread", "suggestion_read"]
