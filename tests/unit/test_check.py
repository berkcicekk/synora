from pathlib import Path

import pytest
from builders import p, r
from thesis import BODY_TEXT, MARGINS, front_matter, h1, main_matter, sect, thesis

from synora.check import CheckResult, Severity, check
from synora.ingest import open_docx
from synora.model import Role
from synora.parse import parse_package
from synora.ruleset import load_ruleset

RULES = load_ruleset(Path(__file__).resolve().parents[2] / "rulesets" / "example.yaml")


def run(data: bytes) -> CheckResult:
    return check(parse_package(open_docx(data)), RULES)


def rule_ids(result: CheckResult) -> set[str]:
    return {f.rule_id for f in result.findings}


def test_compliant_thesis_has_no_findings() -> None:
    result = run(thesis())
    assert [(f.rule_id, f.expected, f.actual) for f in result.findings] == []
    assert result.unknown_paragraphs == 0
    assert result.checked_paragraphs >= 8


def test_roles_of_compliant_thesis() -> None:
    result = run(thesis())
    assert sorted({d.role for d in result.roles.values()}) == sorted({
        Role.HEADING_1, Role.HEADING_2, Role.BODY, Role.FIGURE_CAPTION, Role.TABLE_CAPTION,
        Role.TABLE_CELL, Role.EMPTY, Role.FOOTNOTE, Role.FRONT_MATTER,
    })


# --- Sayfa ------------------------------------------------------------------------------


def test_wrong_paper_and_margins() -> None:
    letter = '<w:pgSz w:w="12240" w:h="15840"/>'
    margins = '<w:pgMar w:top="1440" w:bottom="1417" w:left="1985" w:right="1417"/>'
    body = front_matter() + main_matter().replace(sect("decimal"),
                                                  sect("decimal", page=letter, margins=margins))
    result = run(thesis(body))
    assert rule_ids(result) == {"page.size", "page.margin.top"}
    top = next(f for f in result.findings if f.rule_id == "page.margin.top")
    assert (top.expected, top.actual, top.section_index) == ("3cm", "2.54cm", 1)


def test_left_margin_satisfied_with_gutter() -> None:
    # YTÜ SBE şablonu: sol 2,5 cm + cilt payı 1,5 cm = kılavuzun istediği 4 cm.
    # Word çıktısında metin bloğu soldan left+gutter kadar içeride başlar.
    margins = '<w:pgMar w:top="1701" w:bottom="1417" w:left="1134" w:right="1417" w:gutter="851"/>'
    body = front_matter() + main_matter().replace(sect("decimal"), sect("decimal", margins=margins))
    assert "page.margin.left" not in rule_ids(run(thesis(body)))


def test_left_margin_wrong_even_with_gutter() -> None:
    margins = '<w:pgMar w:top="1701" w:bottom="1417" w:left="1134" w:right="1417" w:gutter="284"/>'
    body = front_matter() + main_matter().replace(sect("decimal"), sect("decimal", margins=margins))
    left = next(f for f in run(thesis(body)).findings if f.rule_id == "page.margin.left")
    assert (left.expected, left.actual) == ("3.5cm", "2cm (cilt payı 0.5cm)")


def test_caption_numbering_sequence() -> None:
    # Şekil/Tablo numaraları sırayı izlemeli: yinelenen, geri giden ya da atlayan numara uyarıdır.
    def cap(text: str) -> str:
        return p(text, ppr='<w:pStyle w:val="Caption"/>')

    def seq_findings(extra: str) -> list[tuple[str, str, str]]:
        result = check(parse_package(open_docx(thesis(front_matter() + main_matter(extra=extra)))),
                       RULES)
        return [(f.rule_id, f.expected, f.actual) for f in result.findings
                if f.rule_id.endswith(".sequence")]

    # Fikstürde Şekil 1.1 ve Tablo 1.1 zaten var; uyumlu devam → bulgu yok.
    assert seq_findings(cap("Şekil 1.2 Ek örnek") + cap("Şekil 2.1 Yeni bölüm")) == []
    # Yinelenen numara
    assert seq_findings(cap("Şekil 1.1 Yinelenen")) == [
        ("figure_caption.sequence", "Şekil 1.2", "Şekil 1.1")]
    # Atlanan numara
    assert seq_findings(cap("Şekil 1.3 Atlanmış")) == [
        ("figure_caption.sequence", "Şekil 1.2", "Şekil 1.3")]
    # Geri giden tablo numarası
    assert seq_findings(cap("Tablo 1.2 Uyumlu") + cap("Tablo 1.1 Geri dönen")) == [
        ("table_caption.sequence", "Tablo 1.3", "Tablo 1.1")]


def test_toc_staleness() -> None:
    # Öğrenci başlığı değiştirir ama Word'de dizini güncellemez: İçindekiler alan sonucu
    # (önbellek) eski kalır. Dizindeki satırlarla gerçek başlıklar karşılaştırılır.
    def toc(*entries: str) -> str:
        return h1("İÇİNDEKİLER") + "".join(p(f"{e} {'.' * 30} {i + 1}")
                                           for i, e in enumerate(entries))

    fresh = (front_matter() + toc("ÖNSÖZ", "GİRİŞ", "1.1 Amaç") + main_matter())
    result = check(parse_package(open_docx(thesis(fresh))), RULES)
    assert "document.toc_stale" not in {f.rule_id for f in result.findings}

    stale = (front_matter() + toc("ÖNSÖZ", "ESKİ BAŞLIK ADI", "1.1 Amaç") + main_matter())
    result = check(parse_package(open_docx(thesis(stale))), RULES)
    stale_findings = [f for f in result.findings if f.rule_id == "document.toc_stale"]
    assert len(stale_findings) == 1 and stale_findings[0].severity.value == "warning"

    # Dizin hiç yoksa bu kural susar (varlık denetimi required_sections'ın işi).
    result = check(parse_package(open_docx(thesis())), RULES)
    assert "document.toc_stale" not in {f.rule_id for f in result.findings}


def test_required_sections() -> None:
    # Kılavuzların en temel maddesi: zorunlu bölümler (ÖZET, KAYNAKLAR…) var mı?
    need = RULES.model_copy(update={"required_sections": ("ÖZET", "KAYNAKLAR")})
    result = check(parse_package(open_docx(thesis())), need)
    missing = {f.expected for f in result.findings if f.rule_id == "document.missing_section"}
    assert missing == {"ÖZET", "KAYNAKLAR"}  # fikstürde ikisi de yok
    # Başlık olarak geçince bulgu düşer; numaralı başlık ve küçük/büyük harf farkı tolere edilir.
    body = (front_matter() + h1("Özet") + p(BODY_TEXT)
            + main_matter(extra=h1("7. KAYNAKLAR") + p("Kaynak girdisi.")))
    result = check(parse_package(open_docx(thesis(body))), need)
    assert not any(f.rule_id == "document.missing_section" for f in result.findings)
    # Alternatif yazımlar: "SONUÇLAR|SONUÇ" — belgede SONUÇ varsa yeter; raporda ilki görünür.
    need = RULES.model_copy(update={"required_sections": ("SONUÇLAR|SONUÇ", "EKLER")})
    body = front_matter() + main_matter(extra=h1("SONUÇ") + p(BODY_TEXT))
    result = check(parse_package(open_docx(thesis(body))), need)
    missing = {f.expected for f in result.findings if f.rule_id == "document.missing_section"}
    assert missing == {"EKLER"}


def test_table_cell_rules_are_enforced_when_defined() -> None:
    # 9 kural seti table_cell kuralı tanımlıyor ama denetim rolü atlıyordu (ölü harf).
    from synora.model import Role
    from synora.ruleset import RoleRules

    cell_rules = RoleRules(size_pt=10)
    with_cells = RULES.model_copy(update={"roles": {**RULES.roles, Role.TABLE_CELL: cell_rules}})
    bad_cell = p(r("Hücre metni", rpr='<w:sz w:val="24"/>'),  # 12 punto; kural 10 istiyor
                 ppr='<w:jc w:val="left"/><w:spacing w:line="240"/>')
    body = front_matter() + main_matter().replace(
        "<w:tbl>", f"<w:tbl><w:tr><w:tc>{bad_cell}</w:tc></w:tr>")
    result = check(parse_package(open_docx(thesis(body))), with_cells)
    assert "table_cell.size_pt" in {f.rule_id for f in result.findings}
    # table_cell kuralı tanımlamayan set (RULES) hücrelere karışmaz.
    plain = check(parse_package(open_docx(thesis(body))), RULES)
    assert not any(f.rule_id.startswith("table_cell") for f in plain.findings)


def test_rule_catalog_only_lists_enforced_rules() -> None:
    # 'Denetlendi ve uygun' listesi, denetimin gerçekten işletmediği bir kuralı iddia edemez.
    from synora.check import SKIPPED_ROLES, rule_catalog
    from synora.model import Role
    from synora.ruleset import RoleRules

    with_dead = RULES.model_copy(
        update={"roles": {**RULES.roles, Role.TEXTBOX: RoleRules(size_pt=10),
                          Role.TABLE_CELL: RoleRules(size_pt=10)}})
    catalog = rule_catalog(with_dead)
    assert Role.TEXTBOX in SKIPPED_ROLES
    assert not any(rid.startswith("textbox.") for rid in catalog)  # atlanan rol: iddia yok
    assert "table_cell.size_pt" in catalog  # artık denetleniyor


def test_page_number_restart_at_format_change() -> None:
    # Kılavuz [roman, arabic] diyorsa ana metin 1'den başlamalı; Word bölüm geçişinde
    # numarayı kendiliğinden sürdürür. start=1 yoksa bulgu.
    no_restart = front_matter() + main_matter().replace(
        sect("decimal"), '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>' + MARGINS
        + '<w:pgNumType w:fmt="decimal"/></w:sectPr>')
    result = check(parse_package(open_docx(thesis(no_restart))), RULES)
    assert "page_numbering.restart" in {f.rule_id for f in result.findings}
    with_restart = front_matter() + main_matter().replace(
        sect("decimal"), '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>' + MARGINS
        + '<w:pgNumType w:fmt="decimal" w:start="1"/></w:sectPr>')
    result = check(parse_package(open_docx(thesis(with_restart))), RULES)
    assert "page_numbering.restart" not in {f.rule_id for f in result.findings}
    # Açık bir başlangıç değeri (ör. kapak sayıldığı için roman iii'ten) bilinçli tercihtir.
    explicit = front_matter() + main_matter().replace(
        sect("decimal"), '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>' + MARGINS
        + '<w:pgNumType w:fmt="decimal" w:start="3"/></w:sectPr>')
    result = check(parse_package(open_docx(thesis(explicit))), RULES)
    assert "page_numbering.restart" not in {f.rule_id for f in result.findings}


def test_chapter_top_margin_rule() -> None:
    # Çankaya/Karabük deseni: kılavuz bölüm başlığını üst kenardan daha aşağıda başlatır;
    # şablonlar bunu bölüm başı bölümlerinde büyük üst kenarla uygular. chapter_top verilince
    # bölüm başlığıyla açılan bölümün üst kenarı ona göre denetlenir, diğerleri top'a göre.
    margins = RULES.page.margins_cm.model_copy(update={"chapter_top": 5.0})
    chapter = RULES.model_copy(
        update={"page": RULES.page.model_copy(update={"margins_cm": margins})})
    big_top = MARGINS.replace('w:top="1701"', 'w:top="2835"')  # 5 cm
    # main_matter bölümü GİRİŞ başlığıyla açılır → üst kenar top (3) YA DA chapter_top (5)
    # olabilir; ön bölüm standart kenarla kalabilir.
    body = front_matter() + main_matter().replace(sect("decimal"),
                                                  sect("decimal", margins=big_top))
    result = check(parse_package(open_docx(thesis(body))), chapter)
    assert "page.margin.top" not in {f.rule_id for f in result.findings}
    # chapter_top tanımlı değilken aynı belge üst kenar bulgusu verir.
    plain = check(parse_package(open_docx(thesis(body))), RULES)
    assert "page.margin.top" in {f.rule_id for f in plain.findings}
    # İkisine de uymayan değer (4 cm) chapter_top ile de bulgudur.
    wrong = MARGINS.replace('w:top="1701"', 'w:top="2268"')
    body = front_matter() + main_matter().replace(sect("decimal"),
                                                  sect("decimal", margins=wrong))
    result = check(parse_package(open_docx(thesis(body))), chapter)
    assert "page.margin.top" in {f.rule_id for f in result.findings}


def test_caption_case_skips_keyword_and_number_prefix() -> None:
    # "Şekil 1.1. Örnek şekil açıklaması" doğru Türkçe: cümle düzeni başlık metnine
    # (keyword + numara sonrasına) uygulanır; "Örnek" yanlış alarm olmamalı.
    from synora.check import case_problems

    assert case_problems("Şekil 1.1. Örnek şekil açıklaması", "sentence") == []
    assert case_problems("Tablo 2.3: Örnek tablo başlığı", "sentence") == []
    assert case_problems("Şekil 1.1. Örnek Şekil Açıklaması", "sentence") != []
    assert case_problems("Şekil 1.1. Örnek Şekil Açıklaması", "title") == []


def test_landscape_section() -> None:
    landscape = '<w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>'
    body = front_matter() + main_matter().replace(sect("decimal"),
                                                  sect("decimal", page=landscape))
    assert rule_ids(run(thesis(body))) == {"page.orientation"}


def test_page_numbering_missing_roman_front_matter() -> None:
    body = h1("ÖNSÖZ") + p(BODY_TEXT, ppr=sect("decimal")) + main_matter()
    result = run(thesis(body))
    assert rule_ids(result) == {"page_numbering.formats"}
    f = result.findings[0]
    assert (f.expected, f.actual) == ("lowerRoman,decimal", "decimal")


def test_missing_section_properties() -> None:
    result = run(thesis(front_matter() + main_matter().replace(sect("decimal"), "")))
    assert "page.size" in rule_ids(result)


# --- Paragraf kuralları -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("ppr", "rpr", "expected_rule", "expected", "actual"),
    [
        ('<w:spacing w:line="240" w:lineRule="auto"/>', "", "body.line_spacing", "1.5", "1.0"),
        ('<w:spacing w:line="240" w:lineRule="exact"/>', "", "body.line_spacing", "1.5",
         "exact:12pt"),
        ('<w:jc w:val="left"/>', "", "body.alignment", "justify", "left"),
        ('<w:ind w:firstLine="0"/>', "", "body.first_line_indent_cm", "1.25", "0"),
        ('<w:spacing w:after="0"/>', "", "body.space_after_pt", "6", "0"),
        ("", '<w:sz w:val="22"/>', "body.size_pt", "12", "11"),
        ("", '<w:rFonts w:ascii="Arial"/>', "body.font", "Times New Roman", "Arial"),
    ],
)
def test_body_violations(ppr: str, rpr: str, expected_rule: str, expected: str,
                         actual: str) -> None:
    bad = p(r(BODY_TEXT, rpr=rpr), ppr=ppr)
    result = run(thesis(front_matter() + main_matter(extra=bad)))
    assert [(f.rule_id, f.expected, f.actual) for f in result.findings] == [
        (expected_rule, expected, actual)
    ]
    f = result.findings[0]
    assert f.role is Role.BODY
    assert f.severity is Severity.ERROR
    assert f.fixable
    assert f.para_index is not None


def test_font_check_covers_every_run() -> None:
    bad = p(r(BODY_TEXT), r("tek kelime", rpr='<w:rFonts w:ascii="Calibri"/>'))
    result = run(thesis(front_matter() + main_matter(extra=bad)))
    assert [(f.rule_id, f.actual) for f in result.findings] == [("body.font", "Calibri")]


def test_heading_not_bold_and_not_on_new_page() -> None:
    heading = p("YÖNTEM", ppr='<w:pStyle w:val="Heading1"/><w:pageBreakBefore w:val="0"/>',
                attrs="")
    heading = heading.replace("<w:r>", '<w:r><w:rPr><w:b w:val="0"/></w:rPr>', 1)
    result = run(thesis(front_matter() + main_matter(extra=heading)))
    assert rule_ids(result) == {"heading_1.bold", "heading_1.page_break_before"}


def test_heading_after_manual_page_break_is_on_new_page() -> None:
    brk = p('<w:r><w:br w:type="page"/></w:r>')
    heading = p("YÖNTEM", ppr='<w:pStyle w:val="Heading1"/><w:pageBreakBefore w:val="0"/>')
    assert run(thesis(front_matter() + main_matter(extra=brk + heading))).findings == ()


def test_footnote_size() -> None:
    from builders import make_docx, notes_xml
    from thesis import STYLES

    notes = notes_xml("footnote", {1: p(r("Dipnot", rpr='<w:sz w:val="24"/>'),
                                        ppr='<w:pStyle w:val="FootnoteText"/>')})
    data = make_docx(front_matter() + main_matter(), styles=STYLES, footnotes=notes)
    result = run(data)
    assert [(f.rule_id, f.role) for f in result.findings] == [("footnote.size_pt", Role.FOOTNOTE)]
    assert result.findings[0].para_index is None


def test_unstyled_numbered_heading_is_recognized_and_checked() -> None:
    # F2'de bu satır "rolü belirsiz" sayılıp atlanıyordu; F3 stilsiz başlıkları tanır.
    fake_heading = p(r("2. YÖNTEM", rpr="<w:b/>"))
    result = run(thesis(front_matter() + main_matter(extra=fake_heading)))
    assert result.unknown_paragraphs == 0
    assert {f.role for f in result.findings} == {Role.HEADING_1}
    # Metin büyük harfle yazıldığı için all_caps bulgusu YOK.
    assert rule_ids(result) == {
        "heading_1.size_pt", "heading_1.alignment", "heading_1.page_break_before",
        "heading_1.space_after_pt",
    }


def test_unstyled_bold_mixed_case_line_stays_unknown() -> None:
    ambiguous = p(r("Araştırmanın sınırlılıkları", rpr="<w:b/>"))
    result = run(thesis(front_matter() + main_matter(extra=ambiguous)))
    assert result.findings == ()
    assert result.unknown_paragraphs == 1


def test_tracked_changes_warning() -> None:
    ins = p(r(BODY_TEXT), f'<w:ins w:id="1" w:author="x">{r(" ek")}</w:ins>')
    result = run(thesis(front_matter() + main_matter(extra=ins)))
    assert [(f.rule_id, f.severity, f.fixable) for f in result.findings] == [
        ("document.tracked_changes", Severity.WARNING, False)
    ]


def test_margins_within_tolerance() -> None:
    near = MARGINS.replace('w:top="1701"', 'w:top="1710"')  # 3,016 cm
    body = front_matter() + main_matter().replace(sect("decimal"), sect("decimal", margins=near))
    assert run(thesis(body)).findings == ()


# --- Kullanıcının rol düzeltmesi ----------------------------------------------------------


def _unknown_pid(result: CheckResult) -> str:
    return next(pid for pid, d in result.roles.items() if d.role is Role.UNKNOWN)


def test_user_role_applies_to_unknown_paragraph() -> None:
    ambiguous = p(r("Araştırmanın sınırlılıkları", rpr="<w:b/>"))
    doc = parse_package(open_docx(thesis(front_matter() + main_matter(extra=ambiguous))))
    pid = _unknown_pid(check(doc, RULES))
    result = check(doc, RULES, user_roles={pid: Role.HEADING_2})
    assert result.unknown_paragraphs == 0
    assert result.roles[pid].role is Role.HEADING_2
    assert {f.para_id for f in result.findings} == {pid}
    assert {f.role for f in result.findings} == {Role.HEADING_2}


def test_user_role_never_overrides_a_classified_paragraph() -> None:
    doc = parse_package(open_docx(thesis()))
    before = check(doc, RULES)
    pid, decision = next((k, d) for k, d in before.roles.items() if d.role is Role.BODY)
    after = check(doc, RULES, user_roles={pid: Role.HEADING_1, "yok": Role.HEADING_1})
    assert after.roles[pid] == decision
    assert after.findings == before.findings
