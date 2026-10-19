"""tools/role_eval.py: stil körleştirmesi ve insan etiketi değerlendirmesi sentetik tezde."""

from __future__ import annotations

import sys
from pathlib import Path

from builders import p, r
from thesis import BODY_TEXT, front_matter, main_matter, thesis

from synora.features import StyleKind, extract_features
from synora.ingest import open_docx
from synora.model import Role
from synora.parse import parse_package

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import role_eval  # noqa: E402


def test_styled_headings_and_captions_are_recovered_without_styles() -> None:
    silver, gold = role_eval.evaluate(thesis())
    wanted = {w for w, _ in silver.pairs}
    assert {Role.HEADING_1, Role.HEADING_2, Role.FIGURE_CAPTION, Role.TABLE_CAPTION} <= wanted
    _, precision, coverage = silver.overall()
    assert (precision, coverage) == (1.0, 1.0), silver.confusion()
    assert gold.pairs == []


def test_blinding_removes_style_signals_only() -> None:
    doc = parse_package(open_docx(thesis()))
    f = next(f for f in extract_features(doc).values() if f.style_kind is StyleKind.HEADING_1)
    b = role_eval.blind(f)
    assert (b.style_kind, b.outline_level) == (StyleKind.NONE, None)
    assert (b.bold, b.size_pt, b.alignment) == (f.bold, f.size_pt, f.alignment)


def test_unstyled_paragraphs_get_no_silver_label() -> None:
    silver, _ = role_eval.evaluate(thesis(front_matter() + main_matter(
        extra=p(r("KALIN SATIR", rpr="<w:b/>")))))
    assert len(silver.pairs) == 5  # ÖNSÖZ, GİRİŞ, 1.1 Amaç ve iki resim yazısı; kalın satır yok


def test_human_labels_are_scored_as_is() -> None:
    doc = parse_package(open_docx(thesis()))
    body = next(x for x in doc.body() if x.text == BODY_TEXT and x.section_index == 1)
    _, gold = role_eval.evaluate(thesis(), {body.para_id: Role.BODY})
    assert gold.pairs == [(Role.BODY, Role.BODY)]


def test_unstyled_heading_guesses_are_counted_for_review() -> None:
    silver, _ = role_eval.evaluate(thesis(front_matter() + main_matter(
        extra=p(r("KALIN ORTALI SATIR", rpr="<w:b/>"), ppr='<w:jc w:val="center"/>'))))
    assert silver.unverified_headings == 1
