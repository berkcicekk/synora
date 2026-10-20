"""Word şablonu üretici (synora.word): kural setinden stilleri hazır .docx.

Ana sözleşme: üretilen şablon kendi kural setinden SIFIR bulguyla geçer. Böylece YAML
değişince şablonun da uyumlu kaldığı sürekli doğrulanır. Çıktı deterministiktir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from synora.check import check
from synora.ingest import open_docx
from synora.parse import parse_package
from synora.ruleset import load_ruleset
from synora.word import build_docx

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["example", "zbeu-tip"])
def test_generated_template_passes_its_own_ruleset(name: str) -> None:
    rules = load_ruleset(ROOT / "rulesets" / f"{name}.yaml")
    data = build_docx(rules)
    result = check(parse_package(open_docx(data)), rules)
    assert [(f.rule_id, f.expected, f.actual) for f in result.findings] == []


def test_every_ruleset_yields_a_clean_template() -> None:
    # Ana sözleşmenin tamamı: 248 kural setinin her biri için üretilen şablon kendi
    # setinden sıfır bulguyla geçer. YAML düzenlemeleri bu testte yakalanır.
    failures: dict[str, list[str]] = {}
    for path in sorted((ROOT / "rulesets").glob("*.yaml")):
        rules = load_ruleset(path)
        result = check(parse_package(open_docx(build_docx(rules))), rules)
        if result.findings:
            failures[path.stem] = [f"{f.rule_id}={f.actual}" for f in result.findings]
    assert failures == {}


def test_output_is_deterministic() -> None:
    rules = load_ruleset(ROOT / "rulesets" / "example.yaml")
    assert build_docx(rules) == build_docx(rules)


def test_no_external_relationships_or_macros() -> None:
    rules = load_ruleset(ROOT / "rulesets" / "zbeu-tip.yaml")
    pkg = open_docx(build_docx(rules))
    assert not pkg.external_relationships
    assert not any("vbaProject" in n for n in pkg.parts)


def test_styles_carry_ruleset_values() -> None:
    rules = load_ruleset(ROOT / "rulesets" / "example.yaml")
    pkg = open_docx(build_docx(rules))
    styles = pkg.parts["word/styles.xml"].decode()
    assert 'w:styleId="Heading1"' in styles
    assert "<w:pageBreakBefore/>" in styles  # heading_1.page_break_before: true
    assert '<w:sz w:val="24"/>' in styles  # body.size_pt: 12
