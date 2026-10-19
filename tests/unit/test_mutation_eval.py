"""tools/mutation_eval.py: kılavuza tam uyan sentetik tezde her bozma yakalanmalı ve
düzeltilmeli; metin hiçbir koşulda değişmemeli. Gerçek belgelerdeki oranlar araçla yerelde
ölçülür (belgeler repoya girmez)."""

from __future__ import annotations

import sys
from pathlib import Path

from thesis import thesis

from synora.ruleset import load_ruleset

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import mutation_eval  # noqa: E402

RULES = load_ruleset(ROOT / "rulesets" / "example.yaml")


def test_every_mutation_on_compliant_thesis_is_detected_and_fixed() -> None:
    tallies = mutation_eval.evaluate(thesis(), RULES, per_type=2)
    expected_kinds = {f"body.{p}" for p in mutation_eval.PARAGRAPH_PROPS if p != "bold"} | {
        "heading_1.bold", "heading_1.size_pt", "page.margin.left", "page.margin.top"}
    assert expected_kinds <= set(tallies), sorted(tallies)
    for kind, t in tallies.items():
        assert t.applied > 0, kind
        assert (t.detected, t.fixed, t.text_changed, t.role_changed) == (
            t.applied, t.applied, 0, 0), (kind, t)


def test_report_has_a_total_line() -> None:
    tallies = mutation_eval.evaluate(thesis(), RULES, per_type=1)
    assert "TOPLAM" in mutation_eval.render(tallies)
