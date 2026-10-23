"""Yönetim paneli (/yonetim): yalnızca listedeki e-posta + oturum başına yönetici anahtarı.

Demo kipinde e-posta doğrulanmadığı için adres tek başına kimlik sayılmaz; yetkisiz herkes 404
görür. Sayfa yalnızca okur ve rapor içeriği (tez başlıkları dahil) göstermez.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_web import SECRET, bad_thesis, csrf_from, login, upload, wait_done
from typer.testing import CliRunner

from synora.cli import app as cli_app
from synora.web.app import create_app
from synora.web.db import Database, tr_day
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ADMIN = "yonetici@beun.edu.tr"
KEY = "dogru-anahtar-0123456789abcdef"


@pytest.fixture
def admin_settings(settings: Settings) -> Settings:
    return replace(settings, admin_emails=(ADMIN,),
                   admin_key_sha256=hashlib.sha256(KEY.encode()).hexdigest())


@pytest.fixture
def admin_client(admin_settings: Settings, mailer: ConsoleMailer) -> Iterator[TestClient]:
    with TestClient(create_app(admin_settings, mailer)) as c:
        yield c


def unlock(client: TestClient, csrf: str, key: str = KEY) -> int:
    res = client.post("/yonetim/anahtar", data={"key": key, "csrf": csrf},
                      follow_redirects=False)
    return res.status_code


# --- Erişim -----------------------------------------------------------------------------------


def test_panel_is_off_without_settings(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer, ADMIN)
    assert client.get("/yonetim").status_code == 404


def test_anonymous_and_other_users_get_404(admin_client: TestClient,
                                           mailer: ConsoleMailer) -> None:
    assert admin_client.get("/yonetim").status_code == 404
    csrf = login(admin_client, mailer)  # listede olmayan öğrenci
    assert admin_client.get("/yonetim").status_code == 404
    assert unlock(admin_client, csrf) == 404  # doğru anahtar bile işe yaramaz
    assert admin_client.get("/yonetim").status_code == 404
    assert 'href="/yonetim"' not in admin_client.get("/").text


def test_admin_email_alone_only_sees_the_key_form(admin_client: TestClient,
                                                  mailer: ConsoleMailer) -> None:
    login(admin_client, mailer, ADMIN)
    assert 'href="/yonetim"' in admin_client.get("/").text
    page = admin_client.get("/yonetim")
    assert page.status_code == 200
    assert 'name="key"' in page.text and 'type="password"' in page.text
    assert "Kayıtlı hesap" not in page.text and ADMIN not in page.text.split("</header>")[1]


def test_wrong_key_keeps_it_locked_and_right_key_opens(admin_client: TestClient,
                                                       mailer: ConsoleMailer) -> None:
    csrf = login(admin_client, mailer, ADMIN)
    res = admin_client.post("/yonetim/anahtar", data={"key": "yanlis", "csrf": csrf})
    assert res.status_code == 400 and "Anahtar yanlış" in res.text
    assert "Kayıtlı hesap" not in admin_client.get("/yonetim").text
    assert unlock(admin_client, csrf) == 303
    assert "Kayıtlı hesap" in admin_client.get("/yonetim").text


def test_key_form_requires_csrf(admin_client: TestClient, mailer: ConsoleMailer) -> None:
    login(admin_client, mailer, ADMIN)
    assert unlock(admin_client, "sahte") == 403
    assert "Kayıtlı hesap" not in admin_client.get("/yonetim").text


def test_key_attempts_are_rate_limited(admin_client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(admin_client, mailer, ADMIN)
    for _ in range(5):
        assert unlock(admin_client, csrf, "yanlis") == 400
    assert unlock(admin_client, csrf) == 429  # sınır dolunca doğru anahtar da beklemeli
    assert "Kayıtlı hesap" not in admin_client.get("/yonetim").text


def test_unlock_belongs_to_the_session(admin_client: TestClient, admin_settings: Settings,
                                       mailer: ConsoleMailer) -> None:
    csrf = login(admin_client, mailer, ADMIN)
    assert unlock(admin_client, csrf) == 303
    # Aynı adresle başka bir tarayıcı (oturum) anahtarsız giremez.
    other = TestClient(admin_client.app)
    login(other, mailer, ADMIN)
    assert "Kayıtlı hesap" not in other.get("/yonetim").text
    # Çıkış yapıp yeniden girince anahtar yeniden sorulur.
    admin_client.post("/logout", data={"csrf": csrf})
    login(admin_client, mailer, ADMIN)
    assert "Kayıtlı hesap" not in admin_client.get("/yonetim").text


# --- İçerik -----------------------------------------------------------------------------------


def test_overview_counts_accounts_and_hides_report_text(admin_client: TestClient,
                                                        mailer: ConsoleMailer) -> None:
    db: Database = admin_client.app.state.db  # type: ignore[attr-defined]
    db.register_user("kayitli@beun.edu.tr", "test")
    db.add_suggestion("Kaynakça denetimi de olsun", "", "/yukle")
    student = TestClient(admin_client.app)
    job_id = upload(student, login(student, mailer), bad_thesis())
    assert wait_done(student, job_id) == "done"

    csrf = login(admin_client, mailer, ADMIN)
    assert unlock(admin_client, csrf) == 303
    html = admin_client.get("/yonetim").text
    assert SECRET not in html  # rapor içeriği (tez metni) yok
    assert "kayitli@beun.edu.tr" in html
    assert "Kaynakça denetimi de olsun" in html
    users = re.search(r'id="n-users">(\d+)<', html)
    jobs = re.search(r'id="n-jobs">(\d+)<', html)
    online = re.search(r'id="n-online">(\d+)<', html)
    assert users and users.group(1) == "1"  # yalnızca kayıt olan; düz giriş hesap açmaz
    assert jobs and jobs.group(1) == "1"
    assert online and online.group(1) == "2"  # öğrenci + yönetici oturumu
    assert "Satır aralığı" in html or "body.line_spacing" in html  # en sık kurallar


def test_daily_job_counter_survives_purge(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = Database(tmp_path / "d.db")
    db.add_job("job-aaaaaaaaaaaaaaaa", "a@beun.edu.tr", "example")
    db.add_job("job-bbbbbbbbbbbbbbbb", "b@beun.edu.tr", "example")
    db.purge(0)
    assert db.get_job("job-aaaaaaaaaaaaaaaa") is None
    today = tr_day(time.time())
    assert db.daily_jobs(today) == {today: 2}
    columns = {r[1] for r in db.execute("PRAGMA table_info(daily_jobs)")}
    assert columns == {"day", "n"}  # e-posta ya da iş kimliği tutulmaz


# --- Ayarlar ve anahtar üretimi ---------------------------------------------------------------


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = hashlib.sha256(KEY.encode()).hexdigest()
    monkeypatch.setenv("SYNORA_ADMIN_EMAILS", " Yonetici@Beun.edu.tr , ikinci@beun.edu.tr")
    monkeypatch.setenv("SYNORA_ADMIN_KEY_SHA256", digest.upper())
    s = Settings.from_env()
    assert s.admin_emails == (ADMIN, "ikinci@beun.edu.tr")
    assert s.admin_key_sha256 == digest and s.admin_enabled
    assert digest not in repr(s)


def test_malformed_key_hash_stops_production(settings: Settings) -> None:
    prod = replace(settings, dev=False, base_url="https://payper.example",
                   admin_emails=(ADMIN,), admin_key_sha256="parola123")
    assert not prod.admin_enabled
    assert any("SYNORA_ADMIN_KEY_SHA256" in p for p in prod.problems())
    # Anahtarsız liste güvenlidir (panel kapalı kalır); açılışı engellemez.
    assert all("ADMIN" not in p for p in replace(prod, admin_key_sha256="").problems())


def test_cli_prints_key_and_matching_hash() -> None:
    out = CliRunner().invoke(cli_app, ["admin-key"]).output
    key = re.search(r"Anahtar[^:]*: (\S+)", out)
    digest = re.search(r"SYNORA_ADMIN_KEY_SHA256=([0-9a-f]{64})", out)
    assert key and digest and len(key.group(1)) >= 32
    assert hashlib.sha256(key.group(1).encode()).hexdigest() == digest.group(1)


def test_key_form_page_is_not_cached(admin_client: TestClient, mailer: ConsoleMailer) -> None:
    login(admin_client, mailer, ADMIN)
    page = admin_client.get("/yonetim")
    assert page.headers["cache-control"] == "no-store"
    assert csrf_from(page.text)
