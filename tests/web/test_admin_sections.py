"""Yönetim paneli bölümleri: sistem durumu, yanlış alarm, kullanım. Hepsi salt okuma; rapor içeriği
(tez metni, başlık yolu) gösterilmez, yeni sayaç kimlik taşımaz.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_web import SECRET, bad_thesis, login, upload, wait_done

from synora.web.app import create_app
from synora.web.db import Database, tr_day
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ADMIN = "yonetici@beun.edu.tr"
KEY = "dogru-anahtar-0123456789abcdef"


@pytest.fixture
def admin_client(settings: Settings, mailer: ConsoleMailer) -> Iterator[TestClient]:
    configured = replace(settings, admin_emails=(ADMIN,), build="abc1234",
                         admin_key_sha256=hashlib.sha256(KEY.encode()).hexdigest())
    with TestClient(create_app(configured, mailer)) as c:
        yield c


def open_panel(client: TestClient, mailer: ConsoleMailer, path: str) -> str:
    csrf = login(client, mailer, ADMIN)
    assert client.post("/yonetim/anahtar", data={"key": KEY, "csrf": csrf},
                       follow_redirects=False).status_code == 303
    return client.get(path).text


# --- Sistem durumu ------------------------------------------------------------------------------


def test_system_section_shows_build_workers_and_queue(admin_client: TestClient,
                                                      mailer: ConsoleMailer) -> None:
    html = open_panel(admin_client, mailer, "/yonetim/sistem")
    assert 'id="sistem"' in html and "abc1234" in html
    assert 'id="s-workers">Çalışıyor<' in html
    assert 'id="s-queue">0 / 20<' in html
    assert 'id="s-uploads">0 / 4<' in html
    assert 'id="s-db">' in html and 'id="s-uptime">' in html


def test_system_section_lists_error_codes_of_last_day(admin_client: TestClient,
                                                      mailer: ConsoleMailer) -> None:
    db: Database = admin_client.app.state.db  # type: ignore[attr-defined]
    db.add_job("job-aaaaaaaaaaaaaaaa", "a@beun.edu.tr", "example")
    db.finish_job("job-aaaaaaaaaaaaaaaa", report=None, error_code="TIMEOUT")
    html = open_panel(admin_client, mailer, "/yonetim/sistem")
    assert "TIMEOUT" in html and "süre sınırını aştı" in html


def test_job_errors_ignore_older_failures(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = Database(tmp_path / "d.db")
    db.add_job("job-aaaaaaaaaaaaaaaa", "a@beun.edu.tr", "example")
    db.finish_job("job-aaaaaaaaaaaaaaaa", report=None, error_code="TIMEOUT")
    assert db.job_errors(time.time() - 60) == [("TIMEOUT", 1)]
    assert db.job_errors(time.time() + 60) == []


# --- Yanlış alarm -------------------------------------------------------------------------------


def test_false_alarm_rows_are_per_ruleset_version_and_sorted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = Database(tmp_path / "d.db")
    for job, rule, verdict in [("j1", "body.line_spacing", "wrong"),
                               ("j2", "body.line_spacing", "wrong"),
                               ("j3", "body.line_spacing", "ok"),
                               ("j4", "page.margins", "wrong"),
                               ("j5", "font.family", "ok")]:
        db.add_feedback(job, "example", 2, rule, None, verdict)
    db.add_feedback("j6", "example", 1, "body.line_spacing", None, "wrong")
    assert db.false_alarms(10) == [
        ("example", 2, "body.line_spacing", 2, 1),
        ("example", 2, "page.margins", 1, 0),  # oy eşitse yeni sürüm önce
        ("example", 1, "body.line_spacing", 1, 0),
    ]  # "yanlış" oyu almayan kural listelenmez


def test_false_alarm_section_shows_rate(admin_client: TestClient, mailer: ConsoleMailer) -> None:
    db: Database = admin_client.app.state.db  # type: ignore[attr-defined]
    for job, verdict in [("j1", "wrong"), ("j2", "wrong"), ("j3", "wrong"), ("j4", "ok")]:
        db.add_feedback(job, "example", 3, "body.line_spacing", None, verdict)
    html = open_panel(admin_client, mailer, "/yonetim/kullanim")
    assert 'id="yanlis-alarm"' in html
    assert "%75" in html and "3 / 4" in html


def test_false_alarm_section_empty_state(admin_client: TestClient, mailer: ConsoleMailer) -> None:
    assert 'Henüz "yanlış" oyu yok' in open_panel(admin_client, mailer, "/yonetim/kullanim")


# --- Kullanım -----------------------------------------------------------------------------------


def test_usage_counter_has_no_identity_and_counts_each_finish_once(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = Database(tmp_path / "d.db")
    columns = {r[1] for r in db.execute("PRAGMA table_info(usage_daily)")}
    assert columns == {"day", "ruleset", "done", "failed", "seconds"}
    db.add_job("job-aaaaaaaaaaaaaaaa", "a@beun.edu.tr", "example")
    db.add_job("job-bbbbbbbbbbbbbbbb", "b@beun.edu.tr", "example")
    db.finish_job("job-aaaaaaaaaaaaaaaa", report="{}", error_code=None, seconds=4.0)
    db.finish_job("job-bbbbbbbbbbbbbbbb", report=None, error_code="TIMEOUT", seconds=9.0)
    # Yürütücünün hata yolu aynı işi ikinci kez bitirebilir: sayaç şişmemeli.
    db.finish_job("job-bbbbbbbbbbbbbbbb", report=None, error_code="INTERNAL")
    # Süre yalnızca başarılı işlerden toplanır (süre aşımı ortalamayı bozmasın).
    assert db.usage_since(tr_day(time.time())) == [("example", 1, 1, 4.0)]


def test_usage_counts_recheck_and_skips_deleted_job(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = Database(tmp_path / "d.db")
    db.add_job("job-aaaaaaaaaaaaaaaa", "a@beun.edu.tr", "example")
    db.finish_job("job-aaaaaaaaaaaaaaaa", report="{}", error_code=None, seconds=1.0)
    db.requeue("job-aaaaaaaaaaaaaaaa")
    db.finish_job("job-aaaaaaaaaaaaaaaa", report="{}", error_code=None, seconds=1.0)
    db.add_job("job-bbbbbbbbbbbbbbbb", "b@beun.edu.tr", "example")
    db.delete_job("job-bbbbbbbbbbbbbbbb")
    db.finish_job("job-bbbbbbbbbbbbbbbb", report="{}", error_code=None, seconds=1.0)
    assert db.usage_since(tr_day(time.time())) == [("example", 2, 0, 2.0)]


def test_usage_survives_report_purge_but_old_days_are_dropped(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = Database(tmp_path / "d.db")
    db.add_job("job-aaaaaaaaaaaaaaaa", "a@beun.edu.tr", "example")
    db.finish_job("job-aaaaaaaaaaaaaaaa", report="{}", error_code=None, seconds=1.0)
    db.execute("INSERT INTO usage_daily VALUES ('2020-01-01', 'eski', 1, 0, 1.0)")
    db.purge(-60)
    assert db.get_job("job-aaaaaaaaaaaaaaaa") is None
    assert db.usage_since("2000-01-01") == [("example", 1, 0, 1.0)]


def test_usage_section_after_real_job_hides_report_text(admin_client: TestClient,
                                                        mailer: ConsoleMailer) -> None:
    student = TestClient(admin_client.app)
    job_id = upload(student, login(student, mailer), bad_thesis())
    assert wait_done(student, job_id) == "done"
    html = open_panel(admin_client, mailer, "/yonetim/kullanim")
    assert 'id="kullanim"' in html and "%100" in html
    assert SECRET not in html


def test_usage_section_empty_state(admin_client: TestClient, mailer: ConsoleMailer) -> None:
    assert "Son 30 günde denetim yok" in open_panel(admin_client, mailer, "/yonetim/kullanim")


# --- Sürüm ayarı --------------------------------------------------------------------------------


def test_build_comes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNORA_BUILD", " 27f6ecf ")
    assert Settings.from_env().build == "27f6ecf"
