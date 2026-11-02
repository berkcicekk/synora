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


def _universities() -> set[str]:
    return set((ROOT / "tools" / "universiteler.txt").read_text(encoding="utf-8").splitlines())


def test_institution_names_come_from_university_list() -> None:
    # Dergi kural setleri (kind: journal) yayıncıya bağlıdır; üniversite listesi tezler içindir.
    from synora.web.app import discover_rulesets

    names = {r.rules.institution for r in discover_rulesets(ROOT / "rulesets").values()
             if r.rules.kind == "thesis"}
    assert names - _universities() - {None} == set()


def test_journal_rulesets_name_a_publisher_not_a_university() -> None:
    from synora.web.app import discover_rulesets

    journals = [r for r in discover_rulesets(ROOT / "rulesets").values()
                if r.rules.kind == "journal"]
    assert journals, "en az bir dergi kural seti bekleniyor (mdpi-electronics)"
    for r in journals:
        assert r.rules.institution, r.id
        assert r.rules.institution not in _universities(), r.id


def test_ruleset_kind_defaults_to_thesis_and_rejects_unknown() -> None:
    import pytest
    from pydantic import ValidationError

    from synora.ruleset import Ruleset

    assert Ruleset(ruleset="x", version=1, name="X").kind == "thesis"
    assert Ruleset(ruleset="x", version=1, name="X", kind="journal").kind == "journal"
    with pytest.raises(ValidationError):
        Ruleset(ruleset="x", version=1, name="X", kind="kitap")


def test_index_counts_universities_and_lists_journals_separately() -> None:
    from synora.web.app import discover_rulesets

    rulesets = [r for r in discover_rulesets(ROOT / "rulesets").values() if r.id != "example"]
    theses = [r for r in rulesets if r.rules.kind == "thesis"]
    universities = {r.rules.institution for r in theses}
    text = rulesets_index.render()
    assert f"**{len(universities)} üniversite · {len(theses)} kural seti**" in text
    main, journals = text.split("## Dergiler", 1)
    assert "`mdpi-electronics`" in journals
    assert "`mdpi-electronics`" not in main
