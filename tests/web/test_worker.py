"""A10: iş ayrı süreçte çalışır; süre aşımında süreç sonlandırılır."""

import json
from pathlib import Path

from thesis import thesis

from synora.web.worker import run_isolated

RULESET = str(Path(__file__).resolve().parents[2] / "rulesets" / "example.yaml")


def test_isolated_run_returns_report() -> None:
    result = run_isolated(thesis(), RULESET, "test-job", timeout=60)
    assert result["error_code"] is None
    assert result["report"] is not None
    assert json.loads(result["report"])["summary"]["errors"] == 0


def test_isolated_run_rejects_bad_file() -> None:
    result = run_isolated(b"zip degil", RULESET, "test-job", timeout=60)
    assert result["report"] is None
    assert result["error_code"] == "NOT_A_ZIP"


def test_timeout_kills_job() -> None:
    result = run_isolated(thesis(), RULESET, "test-job", timeout=0.001)
    assert result["report"] is None
    assert result["error_code"] == "TIMEOUT"


def test_isolated_output_returns_docx() -> None:
    from builders import p
    from thesis import front_matter, main_matter

    from synora.web.worker import output_isolated

    data = thesis(front_matter() + main_matter(extra=p("Kısa.", ppr='<w:jc w:val="left"/>')))
    result = output_isolated("fixed", data, RULESET, "test-job", timeout=60)
    assert result["error_code"] is None
    assert result["docx"] is not None and result["docx"][:2] == b"PK"


def test_worker_survives_unexpected_error(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Bir işte beklenmeyen hata olsa da yürütücü sonraki işleri işlemeye devam eder."""
    import time

    from synora.web.db import Database
    from synora.web.settings import Settings
    from synora.web.worker import JobRunner

    settings = Settings(db_path=tmp_path / "w.db", isolate_jobs=False, workers=1)
    db = Database(settings.db_path)
    runner = JobRunner(db, settings)
    calls = {"n": 0}
    real = runner.run_now

    def flaky(job_id: str, data: bytes, ruleset_path: str,
              user_roles: dict[str, str] | None = None) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("geçici hata")
        real(job_id, data, ruleset_path, user_roles)

    runner.run_now = flaky  # type: ignore[method-assign]
    runner.start()
    try:
        for jid in ("is-1-aaaaaaaaaaaaaaaa", "is-2-bbbbbbbbbbbbbbbb"):
            db.add_job(jid, "a@beun.edu.tr", "example")
            runner.submit(jid, thesis(), RULESET)
        for _ in range(200):
            first, second = db.get_job("is-1-aaaaaaaaaaaaaaaa"), db.get_job("is-2-bbbbbbbbbbbbbbbb")
            if first and second and first.status == "failed" and second.status == "done":
                break
            time.sleep(0.05)
        assert db.get_job("is-1-aaaaaaaaaaaaaaaa").status == "failed"  # type: ignore[union-attr]
        assert db.get_job("is-2-bbbbbbbbbbbbbbbb").status == "done"  # type: ignore[union-attr]
    finally:
        runner.stop()
