"""Resmi enstitü şablonlarıyla saha denemesinde (2026-10-19) görülen desenler, sentetik olarak.

Şablonların kendisi teste konmaz; yalnızca biçim desenleri yeniden üretilir.
"""

from __future__ import annotations

from pathlib import Path

from builders import p, r, style
from test_classify_accuracy import LONG
from thesis import BODY_TEXT, STYLES, front_matter, main_matter, sect, thesis

from synora.check import CheckResult, check
from synora.ingest import open_docx
from synora.model import Role
from synora.parse import parse_package
from synora.roles import assign_roles
from synora.ruleset import load_ruleset

RULES = load_ruleset(Path(__file__).resolve().parents[2] / "rulesets" / "example.yaml")
BRK = p('<w:r><w:br w:type="page"/></w:r>')
CENTER = '<w:jc w:val="center"/><w:ind w:firstLine="0"/>'


def run(data: bytes) -> CheckResult:
    return check(parse_package(open_docx(data)), RULES)


def roles(data: bytes) -> list[tuple[str, Role]]:
    doc = parse_package(open_docx(data))
    decided = assign_roles(doc)
    return [(p.text, decided[p.para_id].role) for p in doc.body() if p.text.strip()]


def line(text: str, rpr: str = "<w:b/>") -> str:
    return p(r(text, rpr=rpr), ppr=CENTER)


# --- Boş satır sayfa başını gizlememeli ------------------------------------------------------

UNBROKEN_H1 = p("YÖNTEM", ppr='<w:pStyle w:val="Heading1"/><w:pageBreakBefore w:val="0"/>')


def test_heading_after_page_break_and_empty_line_is_on_new_page() -> None:
    extra = BRK + p("") + UNBROKEN_H1 + p(BODY_TEXT)
    assert run(thesis(front_matter() + main_matter(extra=extra))).findings == ()


def test_heading_after_section_break_and_empty_lines_is_on_new_page() -> None:
    extra = p(BODY_TEXT, ppr=sect("decimal")) + p("") + p("") + UNBROKEN_H1 + p(BODY_TEXT)
    result = run(thesis(front_matter() + main_matter(extra=extra)))
    assert "heading_1.page_break_before" not in {f.rule_id for f in result.findings}


def test_heading_after_plain_empty_line_still_needs_page_break() -> None:
    extra = p("") + UNBROKEN_H1 + p(BODY_TEXT)
    result = run(thesis(front_matter() + main_matter(extra=extra)))
    assert "heading_1.page_break_before" in {f.rule_id for f in result.findings}


# --- Kapak yalnızca ilk sayfa değil ----------------------------------------------------------

OUTER = (line("T.C.") + line("ZONGULDAK BÜLENT ECEVİT ÜNİVERSİTESİ")
         + line("FEN BİLİMLERİ ENSTİTÜSÜ"))
INNER = (
    line("T.C.") + line("ZONGULDAK BÜLENT ECEVİT ÜNİVERSİTESİ")
    + line("YÜKSEK LİSANS TEZİ", rpr='<w:b/><w:sz w:val="32"/>')
    + line("Ayşe YILMAZ", rpr="") + line("DANIŞMAN: PROF. DR. MEHMET KAYA")
)
APPROVAL = line("KABUL VE ONAY") + p(
    "Ayşe YILMAZ tarafından hazırlanan bu çalışma jürimiz tarafından yüksek lisans tezi "
    "olarak kabul edilmiştir.")


def test_inner_cover_and_approval_pages_are_cover() -> None:
    body = OUTER + BRK + INNER + BRK + APPROVAL + BRK + front_matter() + main_matter()
    decided = roles(thesis(body))
    assert [role for _, role in decided[:10]] == [Role.COVER] * 10, decided[:10]  # 3 + 5 + 2
    assert decided[10] == ("ÖNSÖZ", Role.HEADING_1)
    assert run(thesis(body)).findings == ()


def test_without_front_matter_title_only_first_page_is_cover() -> None:
    # Ön sayfa başlığı (ÖZET, ÖNSÖZ…) bulunmazsa kapak bölgesi genişletilmez: ikinci sayfadaki
    # büyük harfli satır bir bölüm başlığıdır.
    body = OUTER + BRK + p(r("ARAŞTIRMANIN KAPSAMI", rpr="<w:b/>")) + p(LONG) + p(LONG)
    decided = dict(roles(thesis(body)))
    assert decided["ARAŞTIRMANIN KAPSAMI"] is Role.HEADING_1
    assert decided[LONG] is Role.BODY


def test_cover_region_is_limited_to_a_few_pages() -> None:
    chapters = "".join(BRK + p(r(f"KISIM {n}", rpr="<w:b/>")) + p(LONG) for n in "ABCDEF")
    body = OUTER + chapters + BRK + front_matter() + main_matter()
    decided = dict(roles(thesis(body)))
    assert decided["KISIM A"] is Role.HEADING_1


# --- Başlık sanılan satırlar -----------------------------------------------------------------

HEADING4 = style("Heading4", based_on="Normal", name="heading 4",
                 ppr='<w:outlineLvl w:val="3"/>')
HEADING4_STYLES = STYLES.replace("</w:styles>", HEADING4 + "</w:styles>")


def test_fourth_level_heading_is_not_a_chapter_heading() -> None:
    # Kural setlerinde 4. düzey yok: büyük harfli olsa da 1. düzey başlık sayılmamalı.
    h4 = p("ÖRNEK DÖRDÜNCÜ DÜZEY BAŞLIK", ppr='<w:pStyle w:val="Heading4"/>' + CENTER)
    outline = p("BAŞKA BİR DÖRDÜNCÜ DÜZEY", ppr='<w:outlineLvl w:val="3"/>' + CENTER)
    body = front_matter() + main_matter(extra=p(BODY_TEXT) + h4 + p(BODY_TEXT) + outline)
    decided = dict(roles(thesis(body, styles=HEADING4_STYLES)))
    assert decided["ÖRNEK DÖRDÜNCÜ DÜZEY BAŞLIK"] is not Role.HEADING_1
    assert decided["BAŞKA BİR DÖRDÜNCÜ DÜZEY"] is not Role.HEADING_1


def test_plain_centered_caps_line_mid_page_is_not_a_chapter_heading() -> None:
    # ÖZET sayfasının üstündeki tez adı/yazar satırları: büyük harf ama kalın ya da büyük değil.
    plain = line("TEZİN ADI BURADA YER ALIR", rpr="")
    bold = line("KALIN ORTALI BAŞLIK")
    body = front_matter() + main_matter(extra=p(BODY_TEXT) + plain + p(BODY_TEXT) + bold)
    decided = dict(roles(thesis(body)))
    assert decided["TEZİN ADI BURADA YER ALIR"] is Role.UNKNOWN
    assert decided["KALIN ORTALI BAŞLIK"] is Role.HEADING_1


def test_plain_caps_line_at_page_top_is_still_a_chapter_heading() -> None:
    body = front_matter() + main_matter(extra=BRK + line("SONUÇLARIN DEĞERLENDİRİLMESİ", rpr="")
                                        + p(BODY_TEXT))
    assert dict(roles(thesis(body)))["SONUÇLARIN DEĞERLENDİRİLMESİ"] is Role.HEADING_1


# --- Sekmeyle girinti ------------------------------------------------------------------------

TAB_PARAGRAPH = p(f'<w:r><w:tab/><w:t xml:space="preserve">{BODY_TEXT}</w:t></w:r>',
                  ppr='<w:ind w:firstLine="0"/>')


def test_tab_indent_is_a_warning_that_is_not_auto_fixed() -> None:
    # KTÜ kılavuzu girintiyi "1 cm boşluk (sekme)" diye tarif ediyor. Sekme durağının yeri
    # denetlenmiyor; ilk satır girintisi eklemek sekmenin üstüne ikinci girinti olurdu.
    result = run(thesis(front_matter() + main_matter(extra=TAB_PARAGRAPH)))
    [f] = result.findings
    assert (f.rule_id, f.severity.value, f.actual, f.fixable) == (
        "body.first_line_indent_cm", "warning", "sekme", False)


def test_tab_indent_message_explains_what_to_do() -> None:
    from synora.report import to_json
    report = to_json(run(thesis(front_matter() + main_matter(extra=TAB_PARAGRAPH))), RULES)
    assert "sekme" in report.casefold() and "İlk satır" in report


# --- Hiçbir yerde punto yoksa Word 10 pt kullanır --------------------------------------------


def test_size_defaults_to_ten_points_when_nothing_sets_it() -> None:
    from builders import make_docx, styles_xml
    no_size = styles_xml(defaults_rpr='<w:rFonts w:ascii="Times New Roman"/>',
                         styles=style("Normal", default=True, name="Normal"))
    for styles in (no_size, None):
        doc = parse_package(open_docx(make_docx(p(BODY_TEXT), styles=styles)))
        assert doc.body()[0].dominant.size_pt == 10.0
