"""Kapasite sınırları (denetim O2, O4, O6): eğitim tablosu, rapor okuyan rotalar, site geneli
günlük sınır, veritabanı boyutu ve `+etiket` ile kota çoğaltma."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_training import set_role_and_recheck
from test_web import ambiguous_thesis, login, upload, wait_done
from thesis import thesis

from synora.web import worker
from synora.web.app import create_app
from synora.web.db import Database
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
APP_SOURCE = (ROOT / "src" / "synora" / "web" / "app.py").read_text(encoding="utf-8")
ALICE, BOB = "alice@beun.edu.tr", "bob@beun.edu.tr"


def count(db: Database) -> int:
    return int(db.execute("SELECT COUNT(*) FROM training").fetchone()[0])


def row(i: int) -> tuple[str, str, str]:
    return (f'{{"n": {i}}}', "body", "example")


# --- O2: eğitim tablosu ---------------------------------------------------------------------------


def test_identical_training_rows_are_stored_once(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.db")
    db.add_training([row(1), row(1), row(2)])
    db.add_training([row(1)])
    assert count(db) == 2


def test_existing_duplicates_are_removed_when_opening(tmp_path: Path) -> None:
    path = tmp_path / "t.db"
    db = Database(path)
    db.execute("DROP INDEX training_unique")
    db.add_training([row(1), row(1), row(2)])
    assert count(db) == 3
    assert count(Database(path)) == 2


def test_trim_keeps_newest_rows_and_drops_old_ones(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.db")
    db.add_training([row(i) for i in range(5)])
    db.trim_training(keep_rows=3, keep_days=365)
    kept = [r[0] for r in db.execute("SELECT features FROM training ORDER BY rowid").fetchall()]
    assert kept == [row(2)[0], row(3)[0], row(4)[0]]
    db.execute("UPDATE training SET created_at=? WHERE features=?",
               (time.time() - 366 * 86400, row(2)[0]))
    db.trim_training(keep_rows=3, keep_days=365)
    assert count(db) == 2


def test_janitor_trims_training_after_purge(tmp_path: Path, settings: Settings,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    runner = worker.JobRunner(Database(tmp_path / "j.db"),
                              replace(settings, training_keep_rows=1, training_keep_days=9))
    results = iter([False, True])
    monkeypatch.setattr(runner._stop, "wait", lambda _timeout=None: next(results))
    runner.db.add_training([row(1), row(2)])
    runner._janitor()
    assert count(runner.db) == 1


@pytest.mark.parametrize(("cap", "expected"), [(0, 0), (1, 1)])
def test_rows_written_per_recheck_are_capped(settings: Settings, mailer: ConsoleMailer,
                                             cap: int, expected: int) -> None:
    with TestClient(create_app(replace(settings, training_rows_per_job=cap), mailer)) as client:
        set_role_and_recheck(client, mailer, collect=True)
        assert count(client.app.state.db) == expected  # type: ignore[attr-defined]


def test_recheck_with_same_choice_does_not_add_rows(client: TestClient,
                                                    mailer: ConsoleMailer) -> None:
    job_id, csrf = set_role_and_recheck(client, mailer, collect=True)
    res = client.post(f"/jobs/{job_id}/recheck", content=ambiguous_thesis(), headers={
        "X-CSRF-Token": csrf, "Content-Type": "application/octet-stream"})
    assert res.status_code == 202
    assert wait_done(client, job_id) == "done"
    assert count(client.app.state.db) == 1  # type: ignore[attr-defined]


def test_privacy_notice_states_training_retention(client: TestClient, settings: Settings) -> None:
    text = " ".join(client.get("/aydinlatma").text.split())
    assert f"en çok {settings.training_keep_days} gün saklanır" in text
    assert "hesabınız silinse de ayıklanamaz" in text


# --- O4: rapor okuyan rotalar ---------------------------------------------------------------------


def route_body(name: str) -> str:
    return APP_SOURCE.split(f"async def {name}(")[1].split("\n    @app.")[0]


def test_report_is_not_parsed_on_the_event_loop() -> None:
    roles = route_body("job_roles")
    assert "await parse_report(job)" in roles and "json.loads(job.report)" not in roles
    recheck = route_body("job_recheck")
    assert "own_job(" not in recheck and "await load_job(user, job_id)" in recheck


@pytest.fixture
def limited(settings: Settings, mailer: ConsoleMailer) -> Iterator[TestClient]:
    app = create_app(replace(settings, report_writes_per_hour=2), mailer)
    with TestClient(app) as client:
        yield client


def test_role_and_feedback_requests_share_a_per_account_limit(
    limited: TestClient, mailer: ConsoleMailer,
) -> None:
    csrf = login(limited, mailer)
    job_id = upload(limited, csrf, thesis())
    wait_done(limited, job_id)
    headers = {"X-CSRF-Token": csrf}
    assert limited.post(f"/jobs/{job_id}/roles", json={"roles": {}},
                        headers=headers).status_code == 200
    assert limited.post(f"/jobs/{job_id}/feedback", data={"rule_id": "yok", "verdict": "ok"},
                        headers=headers).status_code == 400
    assert limited.post(f"/jobs/{job_id}/roles", json={"roles": {}},
                        headers=headers).status_code == 429
    assert limited.post(f"/jobs/{job_id}/feedback", data={"rule_id": "yok", "verdict": "ok"},
                        headers=headers).status_code == 429
    assert limited.get(f"/jobs/{job_id}").status_code == 200  # okuma etkilenmez


def test_limit_is_per_account(settings: Settings, mailer: ConsoleMailer) -> None:
    app = create_app(replace(settings, report_writes_per_hour=1), mailer)
    with TestClient(app) as alice, TestClient(app) as bob:
        a_csrf = login(alice, mailer, ALICE)
        a_job = upload(alice, a_csrf, thesis())
        wait_done(alice, a_job)
        b_csrf = login(bob, mailer, BOB)
        b_job = upload(bob, b_csrf, thesis())
        wait_done(bob, b_job)
        for client, job, csrf in ((alice, a_job, a_csrf), (bob, b_job, b_csrf)):
            res = client.post(f"/jobs/{job}/roles", json={"roles": {}},
                              headers={"X-CSRF-Token": csrf})
            assert res.status_code == 200


# --- O6: site geneli sınırlar ve kota ------------------------------------------------------------


def test_site_wide_daily_limit_stops_new_jobs(settings: Settings, mailer: ConsoleMailer) -> None:
    app = create_app(replace(settings, max_site_jobs_per_day=1), mailer)
    with TestClient(app) as alice, TestClient(app) as bob:
        wait_done(alice, upload(alice, login(alice, mailer, ALICE), thesis()))
        csrf = login(bob, mailer, BOB)
        res = bob.post("/jobs", content=thesis(), headers={
            "X-CSRF-Token": csrf, "X-Ruleset": "example",
            "Content-Type": "application/octet-stream"})
        assert res.status_code == 503
        assert "Yarın" in res.text


def test_database_size_guard_refuses_new_jobs(settings: Settings, mailer: ConsoleMailer) -> None:
    with TestClient(create_app(replace(settings, max_db_bytes=1), mailer)) as client:
        csrf = login(client, mailer)
        res = client.post("/jobs", content=thesis(), headers={
            "X-CSRF-Token": csrf, "X-Ruleset": "example",
            "Content-Type": "application/octet-stream"})
        assert res.status_code == 503
        assert client.app.state.db.jobs_started_since(0) == 0  # type: ignore[attr-defined]


def test_size_counts_live_data_not_free_pages(tmp_path: Path) -> None:
    """Silinen rapor boş sayfaya döner; boyut kontrolü siteyi kalıcı kapatmamalı."""
    db = Database(tmp_path / "s.db")
    empty = db.used_bytes()
    db.add_job("is-0000000000000000001", ALICE, "example")
    db.finish_job("is-0000000000000000001", report="x" * 2_000_000, error_code=None)
    assert db.used_bytes() > empty + 1_000_000
    db.delete_job("is-0000000000000000001")
    assert db.used_bytes() < empty + 100_000


def test_plus_tag_does_not_multiply_the_daily_quota(tmp_path: Path) -> None:
    db = Database(tmp_path / "q.db")
    db.add_job("is-0000000000000000001", "ali+1@beun.edu.tr", "example")
    db.add_job("is-0000000000000000002", "ali+2@beun.edu.tr", "example")
    assert db.jobs_since("ali@beun.edu.tr", 0) == 2
    assert db.jobs_since("ali+3@beun.edu.tr", 0) == 2
    assert db.jobs_since("veli@beun.edu.tr", 0) == 0


def test_plus_tag_accounts_keep_separate_jobs(tmp_path: Path) -> None:
    db = Database(tmp_path / "q.db")
    db.add_job("is-0000000000000000001", "ali+1@beun.edu.tr", "example")
    assert db.recent_jobs("ali@beun.edu.tr") == []
    assert len(db.recent_jobs("ali+1@beun.edu.tr")) == 1


def test_new_limits_can_be_set_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in (("TRAINING_KEEP_ROWS", "7"), ("TRAINING_KEEP_DAYS", "8"),
                        ("TRAINING_ROWS_PER_JOB", "9"), ("REPORT_WRITES_PER_HOUR", "10"),
                        ("REPORT_WRITES_PER_MINUTE", "11"), ("MAX_SITE_JOBS_PER_DAY", "12"),
                        ("MAX_DB_BYTES", "13")):
        monkeypatch.setenv(f"SYNORA_{name}", value)
    loaded = Settings.from_env()
    assert (loaded.training_keep_rows, loaded.training_keep_days, loaded.training_rows_per_job,
            loaded.report_writes_per_hour, loaded.report_writes_per_minute,
            loaded.max_site_jobs_per_day, loaded.max_db_bytes) == (7, 8, 9, 10, 11, 12, 13)


def test_new_limits_are_documented_in_the_example_environment() -> None:
    example = (ROOT / "deploy" / "synora.env.example").read_text(encoding="utf-8")
    for name in ("MAX_SITE_JOBS_PER_DAY", "MAX_DB_BYTES", "TRAINING_KEEP_ROWS"):
        assert re.search(rf"^#?\s*SYNORA_{name}=", example, re.M), name
