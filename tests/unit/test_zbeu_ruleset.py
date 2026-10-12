"""rulesets/zbeu-tip.yaml: ZBEÜ Tıp Fakültesi kılavuzuna (2019) uyan bir tez temiz çıkmalı."""

from pathlib import Path

from builders import make_docx, notes_xml, p, r, style, styles_xml
from thesis import BODY_TEXT, h1, h2, table

from synora.check import check
from synora.fix import fix_document
from synora.ingest import open_docx
from synora.model import Role
from synora.parse import parse_package
from synora.ruleset import load_ruleset

ROOT = Path(__file__).resolve().parents[2]
RULES = load_ruleset(ROOT / "rulesets" / "zbeu-tip.yaml")

TNR = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>'
NO_INDENT = '<w:ind w:firstLine="0"/>'
STYLES = styles_xml(
    defaults_rpr=TNR + '<w:sz w:val="24"/>',
    styles=(
        style("Normal", default=True, name="Normal",
              ppr='<w:jc w:val="both"/><w:spacing w:line="360" w:lineRule="auto"/>'
                  '<w:ind w:firstLine="567"/>')
        + style("Heading1", based_on="Normal", name="heading 1",
                ppr='<w:jc w:val="center"/><w:pageBreakBefore/>' + NO_INDENT,
                rpr='<w:b/><w:caps/><w:sz w:val="28"/>')
        + style("Heading2", based_on="Normal", name="heading 2",
                ppr='<w:jc w:val="left"/>' + NO_INDENT, rpr="<w:b/>")
        + style("Caption", based_on="Normal", name="caption", ppr=NO_INDENT)
        + style("FootnoteText", based_on="Normal", name="footnote text",
                ppr='<w:spacing w:line="240"/>' + NO_INDENT, rpr='<w:sz w:val="20"/>')
    ),
)
# Kılavuz 3.4: sol 4 cm (2268), üst/alt 3 cm (1701), sağ 2,5 cm (1417)
ZBEU_MARGINS = '<w:pgMar w:top="1701" w:bottom="1701" w:left="2268" w:right="1417"/>'
A4 = '<w:pgSz w:w="11906" w:h="16838"/>'


def sect(fmt: str) -> str:
    return f'<w:sectPr>{A4}{ZBEU_MARGINS}<w:pgNumType w:fmt="{fmt}"/></w:sectPr>'


def zbeu_thesis(extra: str = "") -> bytes:
    body = (
        h1("ÖNSÖZ") + p(BODY_TEXT, ppr=sect("lowerRoman"))
        + h1("GİRİŞ") + p(BODY_TEXT)
        + h2("2.1. Genel Bilgiler")
        + p(r(BODY_TEXT), '<w:r><w:footnoteReference w:id="1"/></w:r>')
        + p("Tablo 2.1. Hasta grupları", ppr='<w:pStyle w:val="Caption"/>') + table()
        + p("Şekil 2.1. Çalışma akışı", ppr='<w:pStyle w:val="Caption"/>')
        + extra
        + sect("decimal")
    )
    notes = notes_xml("footnote", {1: p("Dipnot.", ppr='<w:pStyle w:val="FootnoteText"/>')})
    return make_docx(body, styles=STYLES, footnotes=notes)


def run(data: bytes) -> list[tuple[str, str, str]]:
    result = check(parse_package(open_docx(data)), RULES)
    return [(f.rule_id, f.expected, f.actual) for f in result.findings]


def test_ruleset_values_match_guide() -> None:
    assert RULES.page.size == "A4"
    m = RULES.page.margins_cm
    assert m is not None
    assert (m.top, m.bottom, m.left, m.right) == (3.0, 3.0, 4.0, 2.5)
    assert RULES.fonts.allowed == ("Times New Roman",)
    assert RULES.roles[Role.BODY].first_line_indent_cm == 1.0
    assert RULES.roles[Role.HEADING_1].size_pt == 14
    assert RULES.roles[Role.FOOTNOTE].size_pt == 10


def test_compliant_zbeu_thesis_is_clean() -> None:
    assert run(zbeu_thesis()) == []


def test_common_indent_mistake_is_found_and_fixed() -> None:
    # Pek çok şablonun varsayılanı 1,25 cm; kılavuz 1 cm istiyor.
    data = zbeu_thesis(extra=p(BODY_TEXT, ppr='<w:ind w:firstLine="709"/>'))
    assert run(data) == [("body.first_line_indent_cm", "1", "1.25")]
    fixed = fix_document(data, RULES)
    assert run(fixed.docx) == [("document.tracked_changes", "false", "true")]


def test_left_margin_3_5_is_flagged() -> None:
    margins = ZBEU_MARGINS.replace('w:left="2268"', 'w:left="1985"')  # 3,5 cm
    data = make_docx(h1("GİRİŞ") + p(BODY_TEXT) + f"<w:sectPr>{A4}{margins}</w:sectPr>",
                     styles=STYLES)
    assert ("page.margin.left", "4cm", "3.5cm") in run(data)
