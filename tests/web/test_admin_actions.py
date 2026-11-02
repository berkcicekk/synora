"""Yönetim işlemleri: oturum kapatma, hesap silme, öneri okundu/silme ve işlem kaydı.

Her işlem tam yönetici yetkisi ve CSRF ister; yetkisiz herkes 404 görür. İşlem kaydında ve
yönlendirme adresinde e-posta ya da mesaj metni bulunmaz.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_admin_access import AUD, TEAM, jwk, mint
from test_web import bad_thesis, login, upload, wait_done

from synora.web import access as access_module
from synora.web.app import create_app
from synora.web.db import ADMIN_LOG_KEEP_DAYS, Database, tr_day
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ADMIN = "yonetici@beun.edu.tr"
STUDENT = "ogrenci@beun.edu.tr"
OTHER = "baska@beun.edu.tr"
KEY = "dogru-anahtar-0123456789abcdef"
ROUTES = ["/yonetim/hesap/oturum", "/yonetim/hesap/sil", "/yonetim/oneri/okundu",
          "/yonetim/oneri/sil"]
ACTOR = hashlib.sha256(ADMIN.encode()).hexdigest()[:16]


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


def count(db: Database, sql: str, *params: object) -> int:
    return int(db.execute(sql, params).fetchone()[0])


# --- Yetki ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES)
def test_anonymous_student_and_locked_admin_get_404(client_: TestClient, mailer: ConsoleMailer,
                                                    route: str) -> None:
    db = db_of(client_)
    db.register_user(OTHER, "test")
    db.add_suggestion("mesaj", "", "/")
    assert post(client_, route, csrf="x", email=OTHER, confirm=OTHER, id="1").status_code == 404
    csrf = login(client_, mailer, STUDENT)
    assert post(client_, route, csrf=csrf, email=OTHER, confirm=OTHER, id="1").status_code == 404
    locked = TestClient(client_.app)
    csrf = login(locked, mailer, ADMIN)  # anahtar girilmemiş yönetici
    assert post(locked, route, csrf=csrf, email=OTHER, confirm=OTHER, id="1").status_code == 404
    assert count(db, "SELECT COUNT(*) FROM users WHERE email=?", OTHER) == 1
    assert count(db, "SELECT COUNT(*) FROM suggestions") == 1
    assert db.admin_log() == []


@pytest.mark.parametrize("route", ROUTES)
def test_actions_require_csrf_and_post(client_: TestClient, mailer: ConsoleMailer,
                                       route: str) -> None:
    db = db_of(client_)
    db.register_user(OTHER, "test")
    db.add_suggestion("mesaj", "", "/")
    open_panel(client_, mailer)
    assert post(client_, route, csrf="sahte", email=OTHER, confirm=OTHER, id="1").status_code == 403
    assert post(client_, route, email=OTHER, confirm=OTHER, id="1").status_code == 403
    assert client_.get(route).status_code == 405
    assert count(db, "SELECT COUNT(*) FROM users WHERE email=?", OTHER) == 1
    assert count(db, "SELECT COUNT(*) FROM suggestions") == 1
    assert db.admin_log() == []


# --- Oturum kapatma -------------------------------------------------------------------------------


def test_end_sessions_only_touches_that_account(client_: TestClient,
                                                mailer: ConsoleMailer) -> None:
    db = db_of(client_)
    student = TestClient(client_.app)
    login(student, mailer, STUDENT)
    bystander = TestClient(client_.app)
    login(bystander, mailer, OTHER)
    csrf = open_panel(client_, mailer)
    res = post(client_, "/yonetim/hesap/oturum", csrf=csrf, email=STUDENT.upper())
    assert res.status_code == 303 and "@" not in res.headers["location"]
    assert count(db, "SELECT COUNT(*) FROM sessions WHERE email=?", STUDENT) == 0
    assert count(db, "SELECT COUNT(*) FROM sessions WHERE email=?", OTHER) == 1
    rows = db.admin_log()
    assert len(rows) == 1 and rows[0][1:] == (
        ACTOR, "session_end", hashlib.sha256(STUDENT.encode()).hexdigest()[:16])


def test_end_sessions_without_open_session_logs_nothing(client_: TestClient,
                                                        mailer: ConsoleMailer) -> None:
    csrf = open_panel(client_, mailer)
    res = post(client_, "/yonetim/hesap/oturum", csrf=csrf, email=STUDENT)
    assert res.status_code == 303 and "durum=oturum-yok" in res.headers["location"]
    assert db_of(client_).admin_log() == []


# --- Hesap silme ----------------------------------------------------------------------------------


def seed_account(client: TestClient, mailer: ConsoleMailer) -> str:
    """Öğrencinin kayıt, oturum, iş/rapor, oy, öneri ve giriş bağlantısı izlerini oluşturur."""
    db = db_of(client)
    db.register_user(STUDENT, "test")
    student = TestClient(client.app)
    job_id = upload(student, login(student, mailer, STUDENT), bad_thesis())
    assert wait_done(student, job_id) == "done"
    db.add_feedback(job_id, "example", 1, "body.line_spacing", None, "wrong")
    db.add_suggestion("öğrencinin mesajı", STUDENT.upper(), "/yukle")
    db.add_suggestion("başkasının mesajı", OTHER, "/yukle")
    db.register_user(OTHER, "test")
    return job_id


def test_wrong_confirmation_deletes_nothing(client_: TestClient, mailer: ConsoleMailer) -> None:
    seed_account(client_, mailer)
    csrf = open_panel(client_, mailer)
    res = post(client_, "/yonetim/hesap/sil", csrf=csrf, email=STUDENT, confirm=OTHER)
    assert res.status_code == 303 and "durum=onay" in res.headers["location"]
    res = post(client_, "/yonetim/hesap/sil", csrf=csrf, email=STUDENT)  # onay alanı yok
    assert "durum=onay" in res.headers["location"]
    assert count(db_of(client_), "SELECT COUNT(*) FROM users WHERE email=?", STUDENT) == 1
    assert db_of(client_).admin_log() == []


def test_delete_account_removes_every_trace_but_keeps_anonymous_counters(
        client_: TestClient, mailer: ConsoleMailer) -> None:
    job_id = seed_account(client_, mailer)
    db = db_of(client_)
    today = tr_day(time.time())
    usage = db.usage_since(today)
    daily = db.daily_jobs(today)
    findings = count(db, "SELECT COUNT(*) FROM finding_counts")
    votes = count(db, "SELECT COUNT(*) FROM feedback_counts")
    assert usage and findings and votes

    csrf = open_panel(client_, mailer)
    res = post(client_, "/yonetim/hesap/sil", csrf=csrf, email=STUDENT,
               confirm=f" {STUDENT.upper()} ")
    assert res.status_code == 303 and "durum=silindi" in res.headers["location"]
    assert "@" not in res.headers["location"]

    for sql, param in [("SELECT COUNT(*) FROM users WHERE email=?", STUDENT),
                       ("SELECT COUNT(*) FROM sessions WHERE email=?", STUDENT),
                       ("SELECT COUNT(*) FROM login_tokens WHERE email=?", STUDENT),
                       ("SELECT COUNT(*) FROM jobs WHERE email=?", STUDENT),
                       ("SELECT COUNT(*) FROM feedback WHERE job_id=?", job_id),
                       ("SELECT COUNT(*) FROM job_starts WHERE email_hash=?",
                        hashlib.sha256(STUDENT.encode()).hexdigest()),
                       ("SELECT COUNT(*) FROM suggestions WHERE LOWER(email)=?", STUDENT)]:
        assert count(db, sql, param) == 0, sql
    # Başkası ve anonim sayaçlar etkilenmez.
    assert count(db, "SELECT COUNT(*) FROM users WHERE email=?", OTHER) == 1
    assert count(db, "SELECT COUNT(*) FROM suggestions WHERE email=?", OTHER) == 1
    assert db.usage_since(today) == usage and db.daily_jobs(today) == daily
    assert count(db, "SELECT COUNT(*) FROM finding_counts") == findings
    assert count(db, "SELECT COUNT(*) FROM feedback_counts") == votes
    # Sayfada ve işlem kaydında adres kalmaz.
    html = client_.get(res.headers["location"]).text
    assert STUDENT not in html and "öğrencinin mesajı" not in html
    assert 'class="admin-status" role="status">Hesap ve bağlı veriler silindi' in html
    assert all(STUDENT not in str(r) for r in db.admin_log())
    assert [r[2] for r in db.admin_log()] == ["account_delete"]


def test_delete_flushes_wal_so_reports_do_not_linger(client_: TestClient, mailer: ConsoleMailer,
                                                     admin_settings: Settings) -> None:
    seed_account(client_, mailer)
    csrf = open_panel(client_, mailer)
    post(client_, "/yonetim/hesap/sil", csrf=csrf, email=STUDENT, confirm=STUDENT)
    wal = Path(f"{admin_settings.db_path}-wal")
    # Silmeyi ve WAL boşaltmayı izleyen yazma olmadığı sürece WAL boştur.
    assert not wal.exists() or wal.stat().st_size == 0


def test_delete_unknown_account_reports_not_found(client_: TestClient,
                                                  mailer: ConsoleMailer) -> None:
    csrf = open_panel(client_, mailer)
    for email in (OTHER, "adres-degil"):
        res = post(client_, "/yonetim/hesap/sil", csrf=csrf, email=email, confirm=email)
        assert res.status_code == 303 and "durum=yok" in res.headers["location"]
    assert db_of(client_).admin_log() == []


def test_delete_is_atomic(tmp_path: Path) -> None:
    db = Database(tmp_path / "d.db")
    db.register_user(STUDENT, "test")
    db.add_session("oturum", STUDENT, "csrf", 3600)
    db.execute("DROP TABLE suggestions")  # silme yarıda hata versin
    with pytest.raises(sqlite3.Error):
        db.delete_account(STUDENT, actor=ACTOR, target="hedef")
    assert count(db, "SELECT COUNT(*) FROM users") == 1
    assert count(db, "SELECT COUNT(*) FROM sessions") == 1
    assert db.admin_log() == []
    db.register_user(OTHER, "test")  # bağlantı işlem içinde takılı kalmaz
    assert count(db, "SELECT COUNT(*) FROM users") == 2


def test_job_finishing_after_delete_stores_nothing(tmp_path: Path) -> None:
    db = Database(tmp_path / "d.db")
    db.register_user(STUDENT, "test")
    db.add_job("job-aaaaaaaaaaaaaaaa", STUDENT, "example")
    db.delete_account(STUDENT, actor=ACTOR, target="hedef")
    db.finish_job("job-aaaaaaaaaaaaaaaa", report="{}", error_code=None)
    assert db.get_job("job-aaaaaaaaaaaaaaaa") is None
    assert db.usage_since("2000-01-01") == []


# --- Öneriler -------------------------------------------------------------------------------------


def test_suggestion_read_and_delete(client_: TestClient, mailer: ConsoleMailer) -> None:
    db = db_of(client_)
    db.add_suggestion("birinci mesaj", "", "/")
    db.add_suggestion("ikinci mesaj", "", "/")
    first, second = sorted(r[0] for r in db.admin_suggestions(10))
    csrf = open_panel(client_, mailer)
    assert "2 okunmamış" in client_.get("/yonetim").text

    res = post(client_, "/yonetim/oneri/okundu", csrf=csrf, id=str(first))
    assert res.status_code == 303 and "durum=okundu" in res.headers["location"]
    res = post(client_, "/yonetim/oneri/okundu", csrf=csrf, id=str(first))  # ikinci kez sayılmaz
    assert "durum=yok" in res.headers["location"]
    assert "1 okunmamış" in client_.get("/yonetim").text

    res = post(client_, "/yonetim/oneri/sil", csrf=csrf, id=str(second))
    assert res.status_code == 303 and "durum=oneri-silindi" in res.headers["location"]
    html = client_.get("/yonetim").text
    assert "ikinci mesaj" not in html and "birinci mesaj" in html

    rows = db.admin_log()
    assert [(r[2], r[3]) for r in rows] == [("suggestion_delete", str(second)),
                                            ("suggestion_read", str(first))]
    assert all("mesaj" not in str(r) for r in rows)


@pytest.mark.parametrize("value", ["", "abc", "-1", "1 OR 1=1", "9" * 40])
def test_bad_suggestion_id_changes_nothing(client_: TestClient, mailer: ConsoleMailer,
                                           value: str) -> None:
    db = db_of(client_)
    db.add_suggestion("mesaj", "", "/")
    csrf = open_panel(client_, mailer)
    res = post(client_, "/yonetim/oneri/sil", csrf=csrf, id=value)
    assert res.status_code == 303 and "durum=yok" in res.headers["location"]
    assert count(db, "SELECT COUNT(*) FROM suggestions") == 1


def test_old_database_gains_read_column(tmp_path: Path) -> None:
    path = tmp_path / "eski.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE suggestions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "message TEXT NOT NULL, email TEXT NOT NULL DEFAULT '', "
                 "page TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL)")
    conn.execute("INSERT INTO suggestions (message, created_at) VALUES ('eski', 1.0)")
    conn.commit()
    conn.close()
    rows = Database(path).admin_suggestions(10)
    assert len(rows) == 1 and rows[0][-1] is None


# --- İşlem kaydı ve durum iletisi -----------------------------------------------------------------


def test_admin_log_has_no_identity_columns_and_expires(tmp_path: Path) -> None:
    db = Database(tmp_path / "d.db")
    columns = {r[1] for r in db.execute("PRAGMA table_info(admin_log)")}
    assert columns == {"id", "created_at", "actor", "action", "target"}
    db.add_suggestion("mesaj", "", "/")
    db.delete_suggestion(1, actor=ACTOR)
    old = time.time() - (ADMIN_LOG_KEEP_DAYS + 1) * 86400
    db.execute("INSERT INTO admin_log (created_at, actor, action, target) "
               "VALUES (?, 'a', 'session_end', 't')", (old,))
    db.purge(86400)
    assert [r[2] for r in db.admin_log()] == ["suggestion_delete"]


def test_panel_shows_log_section_and_forms(client_: TestClient, mailer: ConsoleMailer) -> None:
    db = db_of(client_)
    db.register_user(STUDENT, "test")
    db.add_session("ogrenci-oturumu", STUDENT, "csrf", 3600)  # "Oturumu kapat" görünsün
    db.add_suggestion("mesaj", "", "/")
    csrf = open_panel(client_, mailer)
    html = client_.get("/yonetim").text
    assert 'id="islem-kaydi"' in html and "Henüz işlem yok" in html
    for route in ROUTES:
        assert f'action="{route}"' in html
    assert f'name="csrf" value="{csrf}"' in html
    main = html.split("<main")[1].split("</main>")[0]
    assert 'name="confirm"' in main and "<script" not in main and "style=" not in main  # CSP
    res = post(client_, "/yonetim/oneri/okundu", csrf=csrf, id="1")
    assert "Öneri okundu işaretlendi" in client_.get(res.headers["location"]).text
    assert "Öneri okundu işaretlendi" not in client_.get("/yonetim").text  # ileti kalıcı değil
    assert "Henüz işlem yok" not in client_.get("/yonetim").text


def test_status_message_is_allowlisted(client_: TestClient, mailer: ConsoleMailer) -> None:
    open_panel(client_, mailer)
    html = client_.get("/yonetim", params={"durum": "<script>alert(1)</script>"}).text
    assert "alert(1)" not in html
    assert 'class="admin-status"' not in html
    assert '<p class="alert"' not in html
    html = client_.get("/yonetim", params={"durum": "onay"}).text
    assert re.search(r'<p class="alert" role="alert">[^<]*eşleşmedi', html)


# --- Access kipi ----------------------------------------------------------------------------------


@pytest.fixture
def access_client(settings: Settings, mailer: ConsoleMailer,
                  monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(access_module, "fetch_jwks", lambda team: {"keys": [jwk()]})
    configured = replace(settings, admin_emails=(ADMIN,), access_team_domain=TEAM, access_aud=AUD)
    with TestClient(create_app(configured, mailer)) as c:
        yield c


def test_access_mode_action_needs_token_and_page_csrf(access_client: TestClient) -> None:
    db = db_of(access_client)
    db.add_suggestion("mesaj", "", "/")
    headers = {"Cf-Access-Jwt-Assertion": mint()}
    html = access_client.get("/yonetim", headers=headers).text
    found = re.search(r'name="csrf" value="([0-9a-f]{64})"', html)
    assert found
    csrf = found.group(1)
    route = "/yonetim/oneri/okundu"
    data = {"csrf": csrf, "id": "1"}
    assert access_client.post(route, data=data, follow_redirects=False).status_code == 404
    assert access_client.post(route, data={"csrf": "sahte", "id": "1"}, headers=headers,
                              follow_redirects=False).status_code == 403
    other = {"Cf-Access-Jwt-Assertion": mint(email=STUDENT)}
    assert access_client.post(route, data=data, headers=other,
                              follow_redirects=False).status_code == 404
    res = access_client.post(route, data=data, headers=headers, follow_redirects=False)
    assert res.status_code == 303
    assert [r[1] for r in db.admin_log()] == [ACTOR]


def test_access_csrf_does_not_transfer_between_apps(settings: Settings, mailer: ConsoleMailer,
                                                    access_client: TestClient) -> None:
    headers = {"Cf-Access-Jwt-Assertion": mint()}
    db_of(access_client).add_suggestion("mesaj", "", "/")  # form görünsün
    first = re.search(r'name="csrf" value="([0-9a-f]{64})"',
                      access_client.get("/yonetim", headers=headers).text)
    assert first
    configured = replace(settings, admin_emails=(ADMIN,), access_team_domain=TEAM, access_aud=AUD,
                         db_path=Path(f"{settings.db_path}.ikinci"))
    with TestClient(create_app(configured, mailer)) as second:
        db_of(second).add_suggestion("mesaj", "", "/")
        res = second.post("/yonetim/oneri/okundu", data={"csrf": first.group(1), "id": "1"},
                          headers=headers, follow_redirects=False)
    assert res.status_code == 403  # süreç başına rastgele sır
