"""Rapor boyutu sınırlıdır; panel ve durum sorgusu tam raporu hiç okumaz.

Küçük bir dosya on binlerce bulgu üretebilir. Sınır olmasa tek hesap belleği ve diski tüketir.
Kırpılan bulgular sayılardan düşmez: öğrenci toplamı doğru görür.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from builders import p, r
from fastapi.testclient import TestClient
from test_web import bad_thesis, login, upload, wait_done
from thesis import front_matter, main_matter, thesis

from synora.web import pipeline
from synora.web.app import job_error_message, report_view
from synora.web.db import Database
from synora.web.mailer import ConsoleMailer
from synora.web.pipeline import limit_findings, run_pipeline

ROOT = Path(__file__).resolve().parents[2]
RULESET = str(ROOT / "rulesets" / "zbeu-tip.yaml")
STUDENT = "ogrenci@beun.edu.tr"


def finding(rule: str = "body.size_pt", actual: str = "11") -> dict[str, Any]:
    return {"rule_id": rule, "expected": "12", "actual": actual, "severity": "error",
            "fixable": True, "message": "m", "location": "Yer", "block": 1, "role": "body"}


def many_bad_paragraphs(n: int) -> bytes:
    bad = "".join(p(r(f"Paragraf {i}"), ppr='<w:spacing w:line="240"/>') for i in range(n))
    return thesis(front_matter() + main_matter(extra=bad))


# --- Kırpma kuralı --------------------------------------------------------------------------------


def test_same_kind_findings_are_capped_but_still_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "MAX_FINDINGS_PER_GROUP", 3)
    kept, dropped = limit_findings([finding() for _ in range(10)] + [finding(actual="10")])
    assert len(kept) == 4 and dropped == 0
    assert [f.get("omitted", 0) for f in kept] == [0, 0, 7, 0]


def test_total_cap_counts_what_it_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "MAX_FINDINGS_PER_GROUP", 2)
    monkeypatch.setattr(pipeline, "MAX_REPORT_FINDINGS", 3)
    # Her bulgu ayrı tür: tür sınırı işe yaramaz, toplam sınır yakalar.
    kept, dropped = limit_findings([finding(actual=str(i)) for i in range(10)])
    assert len(kept) == 3 and dropped == 7


def test_total_cap_keeps_omitted_counts_of_dropped_findings(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "MAX_FINDINGS_PER_GROUP", 1)
    monkeypatch.setattr(pipeline, "MAX_REPORT_FINDINGS", 1)
    kept, dropped = limit_findings([finding("a"), finding("b"), finding("b"), finding("b")])
    assert len(kept) == 1 and dropped == 3  # "b": 1 tutulan + 2 kırpılan


def test_nothing_changes_under_the_limits() -> None:
    findings = [finding(), finding(actual="10")]
    assert limit_findings([dict(f) for f in findings]) == (findings, 0)


def test_report_view_shows_true_counts() -> None:
    kept = finding()
    kept["omitted"] = 7
    view = report_view({"summary": {}, "ruleset": {}, "findings": [kept], "dropped_findings": 5})
    assert view["cards"][0]["count"] == 8 and view["cards"][0]["omitted"] == 7
    assert view["finding_count"] == 8 and view["dropped_findings"] == 5


def test_old_reports_without_limit_fields_still_render() -> None:
    view = report_view({"summary": {}, "ruleset": {}, "findings": [finding()]})
    assert view["cards"][0]["omitted"] == 0 and view["dropped_findings"] == 0


# --- Denetim ----------------------------------------------------------------------------------


def test_pipeline_caps_report_and_keeps_full_totals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "MAX_FINDINGS_PER_GROUP", 5)
    outcome = run_pipeline(many_bad_paragraphs(300), RULESET)
    assert outcome["report"] and outcome["stats"]
    report = json.loads(outcome["report"])
    stats = json.loads(outcome["stats"])
    kinds = {(f["rule_id"], f["expected"], f["actual"]) for f in report["findings"]}
    assert len(report["findings"]) <= 5 * len(kinds)
    assert stats["findings"] >= 300 and sum(stats["rule_counts"].values()) == stats["findings"]
    assert stats["errors"] == report["summary"]["errors"]
    shown = sum(1 + f.get("omitted", 0) for f in report["findings"])
    assert shown + report["dropped_findings"] == stats["findings"]


def test_report_over_byte_limit_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "MAX_REPORT_BYTES", 100)
    outcome = run_pipeline(bad_thesis(), RULESET)
    assert outcome["report"] is None and outcome["stats"] is None
    assert outcome["error_code"] == "REPORT_TOO_LARGE"
    assert "biçim farkı" in job_error_message("REPORT_TOO_LARGE")


def test_failed_pipeline_has_no_stats() -> None:
    outcome = run_pipeline(b"zip degil", RULESET)
    assert outcome["report"] is None and outcome["stats"] is None


# --- Panel ve durum tam raporu okumaz ------------------------------------------------------------


def finished_job(client: TestClient, mailer: ConsoleMailer) -> tuple[Database, str]:
    job_id = upload(client, login(client, mailer, STUDENT), bad_thesis())
    assert wait_done(client, job_id) == "done"
    return client.app.state.db, job_id  # type: ignore[attr-defined]


def test_panel_and_status_never_parse_the_report(client: TestClient,
                                                 mailer: ConsoleMailer) -> None:
    db, job_id = finished_job(client, mailer)
    expected = json.loads(db.get_job(job_id).stats)["findings"]  # type: ignore[arg-type,union-attr]
    db.execute("UPDATE jobs SET report='{bozuk' WHERE id=?", (job_id,))
    panel = client.get("/")
    assert panel.status_code == 200 and "Denetim raporu" in panel.text
    assert f'<span class="bignum">{expected}</span>' in panel.text
    assert client.get(f"/jobs/{job_id}/status").json() == {"status": "done"}
    assert client.get("/yukle").status_code == 200


def test_listing_queries_do_not_load_report(client: TestClient, mailer: ConsoleMailer) -> None:
    db, job_id = finished_job(client, mailer)
    assert db.get_job(job_id).report  # type: ignore[union-attr]
    assert db.get_job_meta(job_id).report is None  # type: ignore[union-attr]
    assert db.get_job_meta("yok") is None
    assert [j.report for j in db.recent_jobs(STUDENT)] == [None]


def test_anonymous_counter_uses_full_totals(client: TestClient, mailer: ConsoleMailer) -> None:
    db, job_id = finished_job(client, mailer)
    rule_counts = json.loads(db.get_job(job_id).stats)["rule_counts"]  # type: ignore[arg-type,union-attr]
    stored = dict(db.execute("SELECT rule_id, n FROM finding_counts"))
    assert stored == rule_counts


def test_old_done_job_without_stats_keeps_panel_working(client: TestClient,
                                                        mailer: ConsoleMailer) -> None:
    db, job_id = finished_job(client, mailer)
    db.execute("UPDATE jobs SET stats=NULL WHERE id=?", (job_id,))
    panel = client.get("/")
    assert panel.status_code == 200 and "hazır" in panel.text
    assert f'href="/jobs/{job_id}"' in panel.text


def test_old_database_gains_stats_column(tmp_path: Path) -> None:
    path = tmp_path / "eski.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, email TEXT NOT NULL, "
                 "ruleset TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, "
                 "finished_at REAL, error_code TEXT, report TEXT)")
    conn.commit()
    conn.close()
    db = Database(path)
    db.add_job("job-aaaaaaaaaaaaaaaa", STUDENT, "example")
    db.finish_job("job-aaaaaaaaaaaaaaaa", report="{}", error_code=None, stats='{"findings": 0}')
    assert db.get_job_meta("job-aaaaaaaaaaaaaaaa").stats == '{"findings": 0}'  # type: ignore[union-attr]


# --- Arayüz ---------------------------------------------------------------------------------------


def test_job_page_explains_trimmed_findings(client: TestClient, mailer: ConsoleMailer) -> None:
    db, job_id = finished_job(client, mailer)
    report = json.loads(db.get_job(job_id).report)  # type: ignore[arg-type,union-attr]
    report["findings"][0]["omitted"] = 40
    report["dropped_findings"] = 12
    db.execute("UPDATE jobs SET report=? WHERE id=?", (json.dumps(report), job_id))
    html = client.get(f"/jobs/{job_id}").text
    assert "12 bulgu listede gösterilmiyor" in html
    assert "40 yer daha" in html


def test_too_large_failure_page_gives_useful_steps(client: TestClient,
                                                   mailer: ConsoleMailer) -> None:
    db, job_id = finished_job(client, mailer)
    db.execute("UPDATE jobs SET status='failed', report=NULL, error_code='REPORT_TOO_LARGE' "
               "WHERE id=?", (job_id,))
    html = client.get(f"/jobs/{job_id}").text
    assert "tek bir stil" in html and "Word onarmayı önerirse" not in html
