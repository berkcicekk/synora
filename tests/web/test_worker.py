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
    assert result == {"report": None, "error_code": "NOT_A_ZIP"}


def test_timeout_kills_job() -> None:
    result = run_isolated(thesis(), RULESET, "test-job", timeout=0.001)
    assert result == {"report": None, "error_code": "TIMEOUT"}
