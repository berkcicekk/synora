"""Ö1 — "Bu bulgu yanlış mı?" geri bildirimi: POST /jobs/{id}/feedback.

Metin saklanmaz: yalnızca rule_id, verdict ve kural seti sürümü. İş silinince işe bağlı
kayıt gider; kural seti sürümüne bağlı toplu sayım kalır (pilot yanlış alarm ölçüsü).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from test_web import bad_thesis, login, upload, wait_done

from synora.web.db import Database
from synora.web.mailer import ConsoleMailer


def ready_job(client: TestClient, mailer: ConsoleMailer) -> tuple[str, str]:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, bad_thesis())
    assert wait_done(client, job_id) == "done"
    return job_id, csrf


def send(client: TestClient, job_id: str, csrf: str, **data: str):
    return client.post(f"/jobs/{job_id}/feedback", data=data,
                       headers={"X-CSRF-Token": csrf})


def counts(client: TestClient) -> list[tuple]:
    db: Database = client.app.state.db  # type: ignore[attr-defined]
    return db.execute(
        "SELECT ruleset, rule_id, verdict, n FROM feedback_counts ORDER BY rule_id").fetchall()


def test_feedback_is_recorded_without_text(client: TestClient, mailer: ConsoleMailer) -> None:
    job_id, csrf = ready_job(client, mailer)
    res = send(client, job_id, csrf, rule_id="body.line_spacing", verdict="wrong")
    assert res.status_code == 200
    rows = counts(client)
    assert rows == [("example", "body.line_spacing", "wrong", 1)]


def test_duplicate_feedback_counts_once(client: TestClient, mailer: ConsoleMailer) -> None:
    job_id, csrf = ready_job(client, mailer)
    for _ in range(2):
        assert send(client, job_id, csrf,
                    rule_id="body.line_spacing", verdict="wrong").status_code == 200
    assert counts(client)[0][3] == 1


def test_feedback_requires_csrf_and_valid_verdict(
        client: TestClient, mailer: ConsoleMailer) -> None:
    job_id, csrf = ready_job(client, mailer)
    no_csrf = client.post(f"/jobs/{job_id}/feedback",
                          data={"rule_id": "body.line_spacing", "verdict": "wrong"})
    assert no_csrf.status_code == 403
    bad_verdict = send(client, job_id, csrf, rule_id="body.line_spacing", verdict="evil")
    assert bad_verdict.status_code == 400
    bad_rule = send(client, job_id, csrf, rule_id="<script>", verdict="wrong")
    assert bad_rule.status_code == 400
    assert counts(client) == []


def test_aggregate_survives_job_deletion(client: TestClient, mailer: ConsoleMailer) -> None:
    job_id, csrf = ready_job(client, mailer)
    send(client, job_id, csrf, rule_id="body.line_spacing", verdict="wrong")
    db: Database = client.app.state.db  # type: ignore[attr-defined]
    res = client.post(f"/jobs/{job_id}/delete",
                      data={"csrf": csrf})
    assert res.status_code in (200, 303)
    assert db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
    assert counts(client)[0][3] == 1  # toplu sayım kalır


def test_report_page_offers_feedback_button(client: TestClient, mailer: ConsoleMailer) -> None:
    job_id, _ = ready_job(client, mailer)
    html = client.get(f"/jobs/{job_id}").text
    assert "data-feedback=" in html


def test_demo_has_no_feedback_button(client: TestClient) -> None:
    assert "data-feedback=" not in client.get("/demo").text
