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
