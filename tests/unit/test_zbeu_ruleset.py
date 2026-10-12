"""rulesets/zbeu-tip.yaml: ZBEÜ Tıp Fakültesi kılavuzuna (2019) uyan bir tez temiz çıkmalı."""

from pathlib import Path

import pytest
from builders import hdr_xml, make_docx, notes_xml, p, r, style, styles_xml
from thesis import BODY_TEXT, h1, h2, table

from synora.check import Severity, case_problems, check
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


FOOTER_REF = '<w:footerReference w:type="default" r:id="rIdF"/>'


def sect(fmt: str) -> str:
    return f'<w:sectPr>{FOOTER_REF}{A4}{ZBEU_MARGINS}<w:pgNumType w:fmt="{fmt}"/></w:sectPr>'


def page_field(before: str = "", after: str = "") -> str:
    return (
        (r(before) if before else "")
        + '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        + "<w:r><w:instrText> PAGE </w:instrText></w:r>"
        + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + r("1")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        + (r(after) if after else "")
    )


RIGHT_FOOTER = hdr_xml(p(page_field(), ppr='<w:jc w:val="right"/>'), tag="ftr")
FIGURE = p('<w:r><w:drawing/></w:r>', ppr='<w:jc w:val="center"/>' + NO_INDENT)


def zbeu_thesis(extra: str = "", footer: str = RIGHT_FOOTER) -> bytes:
    body = (
        h1("ÖNSÖZ") + p(BODY_TEXT, ppr=sect("lowerRoman"))
        + h1("GİRİŞ") + p(BODY_TEXT)
        + h2("2.1. Genel Bilgiler")
        + p(r(BODY_TEXT), '<w:r><w:footnoteReference w:id="1"/></w:r>')
        + p("Tablo 2.1. Hasta grupları", ppr='<w:pStyle w:val="Caption"/>') + table()
        + FIGURE
        + p("Şekil 2.1. Çalışma akışı", ppr='<w:pStyle w:val="Caption"/>')
        + extra
        + sect("decimal")
    )
    notes = notes_xml("footnote", {1: p("Dipnot.", ppr='<w:pStyle w:val="FootnoteText"/>')})
    return make_docx(body, styles=STYLES, footnotes=notes, footers={"rIdF": footer})


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


# --- Ön sayfalar ------------------------------------------------------------------------------


def test_single_spaced_preface_is_allowed() -> None:
    # Kılavuz 5.3: önsöz "gerekirse bir satır aralıklı yazılabilir".
    single = p(BODY_TEXT, ppr='<w:spacing w:line="240"/>')
    data = make_docx(
        h1("ÖNSÖZ") + single + p(BODY_TEXT, ppr=sect("lowerRoman"))
        + h1("GİRİŞ") + p(BODY_TEXT) + sect("decimal"),
        styles=STYLES, footers={"rIdF": RIGHT_FOOTER})
    assert run(data) == []


def test_single_spacing_in_body_is_still_an_error() -> None:
    data = zbeu_thesis(extra=p(BODY_TEXT, ppr='<w:spacing w:line="240"/>'))
    assert run(data) == [("body.line_spacing", "1.5", "1.0")]


# --- Sayfa numarası -----------------------------------------------------------------------------


def test_centered_page_number_is_found_and_fixed() -> None:
    footer = hdr_xml(p(page_field(), ppr='<w:jc w:val="center"/>'), tag="ftr")
    data = zbeu_thesis(footer=footer)
    assert run(data) == [("page_numbering.position", "bottom_right", "bottom_center")]
    fixed = fix_document(data, RULES)
    assert run(fixed.docx) == [("document.tracked_changes", "false", "true")]


def test_tab_aligned_page_number_is_not_auto_fixed() -> None:
    footer = hdr_xml(p('<w:r><w:tab/></w:r>' + page_field()), tag="ftr")  # sekmeyle ortalama
    data = zbeu_thesis(footer=footer)
    result = check(parse_package(open_docx(data)), RULES)
    found = [(f.rule_id, f.actual, f.fixable) for f in result.findings]
    assert found == [("page_numbering.position", "bottom_center", False)]


def test_page_number_in_header_is_flagged() -> None:
    header = hdr_xml(p(page_field(), ppr='<w:jc w:val="right"/>'))
    body = (h1("GİRİŞ") + p(BODY_TEXT)
            + f'<w:sectPr><w:headerReference w:type="default" r:id="rIdH"/>{A4}{ZBEU_MARGINS}'
              '</w:sectPr>')
    data = make_docx(body, styles=STYLES, headers={"rIdH": header})
    assert ("page_numbering.position", "bottom_right", "top_right") in run(data)


def test_parenthesised_page_number_is_flagged() -> None:
    footer = hdr_xml(p(page_field("(", ")"), ppr='<w:jc w:val="right"/>'), tag="ftr")
    assert run(zbeu_thesis(footer=footer)) == [("page_numbering.decoration", "none", "decorated")]


def test_missing_page_number() -> None:
    footer = hdr_xml(p("Zonguldak"), tag="ftr")
    assert run(zbeu_thesis(footer=footer)) == [("page_numbering.position", "bottom_right",
                                                "missing")]


def test_footer_inherited_by_later_sections() -> None:
    # İkinci bölümün kendi altbilgi başvurusu yok: Word öncekini devralır, bulgu tekrarlanmamalı.
    footer = hdr_xml(p(page_field(), ppr='<w:jc w:val="center"/>'), tag="ftr")
    no_ref = f'<w:sectPr>{A4}{ZBEU_MARGINS}<w:pgNumType w:fmt="decimal"/></w:sectPr>'
    body = (h1("ÖNSÖZ") + p(BODY_TEXT, ppr=sect("lowerRoman"))
            + h1("GİRİŞ") + p(BODY_TEXT) + no_ref)
    data = make_docx(body, styles=STYLES, footers={"rIdF": footer})
    found = [f for f in run(data) if f[0] == "page_numbering.position"]
    assert found == [("page_numbering.position", "bottom_right", "bottom_center")]
    result = check(parse_package(open_docx(data)), RULES)
    assert [f.section_index for f in result.findings
            if f.rule_id == "page_numbering.position"] == [0]


# --- Şekil/tablo başlığının yeri ------------------------------------------------------------------


def test_table_caption_below_table_is_flagged_not_fixable() -> None:
    body = (h1("GİRİŞ") + p(BODY_TEXT) + table()
            + p("Tablo 1.1. Hasta grupları", ppr='<w:pStyle w:val="Caption"/>')
            + sect("decimal"))
    data = make_docx(body, styles=STYLES, footers={"rIdF": RIGHT_FOOTER})
    result = check(parse_package(open_docx(data)), RULES)
    pos = [(f.rule_id, f.expected, f.actual, f.fixable) for f in result.findings
           if f.rule_id.endswith("position")]
    assert pos == [("table_caption.position", "above", "below", False)]


def test_figure_caption_above_figure_is_flagged() -> None:
    body = (h1("GİRİŞ") + p(BODY_TEXT)
            + p("Şekil 1.1. Çalışma akışı", ppr='<w:pStyle w:val="Caption"/>')
            + p("") + FIGURE + sect("decimal"))
    data = make_docx(body, styles=STYLES, footers={"rIdF": RIGHT_FOOTER})
    assert ("figure_caption.position", "below", "above") in run(data)


# --- Başlık harfi -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "mode", "bad"),
    [
        ("2.1. Araştırmanın Amacı ve Önemi", "title", []),
        ("2.1. Araştırmanın amacı", "title", ["amacı"]),
        ("2.1. Gereç Ve Yöntem", "title", ["Ve"]),
        ("2.1. Türkiye'deki Uygulamalar ile Sonuçlar", "title", []),
        ("2.1. BT ve MR Bulguları", "title", []),
        ("2.1. GENEL BİLGİLER", "title", ["TAMAMI BÜYÜK HARF"]),
        ("2.1.1. Hasta grubunun seçimi", "sentence", []),
        ("2.1.1. Hasta Grubunun Seçimi", "sentence", ["Grubunun", "Seçimi"]),
        ("2.1.1. hasta grubu", "sentence", ["hasta"]),
        ("2.1.1. İstatistiksel analiz ve SPSS", "sentence", []),
    ],
)
def test_case_problems(text: str, mode: str, bad: list[str]) -> None:
    assert case_problems(text, mode) == bad


def test_heading_case_is_a_warning() -> None:
    data = zbeu_thesis(extra=h2("2.2. Hasta grubu ve yöntem"))
    result = check(parse_package(open_docx(data)), RULES)
    case = [(f.rule_id, f.severity, f.fixable, f.actual) for f in result.findings]
    assert case == [("heading_2.case", Severity.WARNING, False, "grubu|yöntem")]
