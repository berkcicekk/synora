"""Editör görünümü için belge iskeleti: yapı doğru, gövde metni yok, bulgular bloklara bağlı."""

import itertools
import json
from pathlib import Path

from builders import p, r
from thesis import front_matter, main_matter, thesis

from synora.web.pipeline import run_pipeline

RULESET = str(Path(__file__).resolve().parents[2] / "rulesets" / "example.yaml")
SECRET = "Bu cümle tezin gizli gövde metnidir ve rapora girmemelidir"


def report(data: bytes) -> dict:  # type: ignore[type-arg]
    result = run_pipeline(data, RULESET)
    assert result["report"] is not None
    return json.loads(result["report"])  # type: ignore[no-any-return]


def test_outline_structure_and_privacy() -> None:
    bad = p(r(SECRET), ppr='<w:spacing w:line="240"/>')
    rep = report(thesis(front_matter() + main_matter(extra=bad)))
    blocks = rep["document"]
    kinds = [b["kind"] for b in blocks]
    assert kinds[0] == "section"
    assert "table" in kinds and "caption" in kinds and "notes" in kinds
    headings = [b["text"] for b in blocks if b["kind"] in ("h1", "h2")]
    assert headings == ["ÖNSÖZ", "GİRİŞ", "1.1 Amaç"]
    raw = json.dumps(rep, ensure_ascii=False)
    assert SECRET not in raw
    assert "sentetik bir gövde metnidir" not in raw  # thesis.BODY_TEXT


def test_findings_point_to_blocks() -> None:
    bad = p(r(SECRET), ppr='<w:spacing w:line="240"/>')
    rep = report(thesis(front_matter() + main_matter(extra=bad)))
    finding = next(f for f in rep["findings"] if f["rule_id"] == "body.line_spacing")
    block = rep["document"][finding["block"]]
    assert block["kind"] == "para"
    assert block["lines"] >= 1


def test_no_consecutive_page_breaks() -> None:
    brk = p('<w:r><w:br w:type="page"/></w:r>')
    rep = report(thesis(front_matter() + main_matter(extra=brk + brk)))
    kinds = [b["kind"] for b in rep["document"]]
    assert all(not (a == b == "pagebreak") for a, b in itertools.pairwise(kinds))
