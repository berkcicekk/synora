"""rulesets/KAYNAKLAR.md kural setleriyle eşleşmeli; tüm kural setleri geçerli olmalı."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import rulesets_index  # noqa: E402
import validate_rulesets  # noqa: E402


def test_index_is_up_to_date() -> None:
    current = (ROOT / "rulesets" / "KAYNAKLAR.md").read_text(encoding="utf-8")
    assert current == rulesets_index.render(), (
        "rulesets/KAYNAKLAR.md eski: python -m uv run python tools/rulesets_index.py")


def test_all_rulesets_validate() -> None:
    problems = {p.name: validate_rulesets.validate(p)
                for p in sorted((ROOT / "rulesets").glob("*.yaml"))}
    assert {k: v for k, v in problems.items() if v} == {}


def test_institution_names_come_from_university_list() -> None:
    from synora.web.app import discover_rulesets

    universities = set((ROOT / "tools" / "universiteler.txt").read_text(encoding="utf-8")
                       .splitlines())
    names = {r.rules.institution for r in discover_rulesets(ROOT / "rulesets").values()}
    assert names - universities - {None} == set()
