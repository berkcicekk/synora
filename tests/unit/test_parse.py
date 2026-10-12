import pytest
from builders import (
    hdr_xml,
    make_docx,
    notes_xml,
    numbering_xml,
    p,
    r,
    style,
    styles_xml,
    theme_xml,
)

from synora.errors import ErrorCode, ParseError
from synora.ingest import open_docx
from synora.model import Alignment, DocModel, LineRule, LineSpacing, Story
from synora.parse import parse_package

SECRET = "GİZLİ TEZ CÜMLESİ"


def model(body: str, **kw: str | dict[str, str] | None) -> DocModel:
    return parse_package(open_docx(make_docx(body, **kw)))  # type: ignore[arg-type]


TNR_12 = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/><w:sz w:val="24"/>'


# --- Stil kalıtımı -------------------------------------------------------------------


def test_style_chain_and_doc_defaults() -> None:
    styles = styles_xml(
        defaults_rpr=TNR_12,
        styles=style("Normal", default=True)
        + style("Heading1", based_on="Normal", ppr='<w:jc w:val="center"/>',
                rpr='<w:b/><w:sz w:val="28"/>', name="heading 1"),
    )
    para = model(p("Giriş", ppr='<w:pStyle w:val="Heading1"/>'), styles=styles).paragraphs[0]
    assert para.style_id == "Heading1"
    assert para.style_name == "heading 1"
    assert para.props.alignment is Alignment.CENTER
    assert para.dominant.size_pt == 14
    assert para.dominant.bold is True
    assert para.dominant.font == "Times New Roman"


def test_direct_formatting_wins() -> None:
    styles = styles_xml(defaults_rpr=TNR_12, styles=style("Normal", default=True))
    para = model(p(r("metin", rpr='<w:sz w:val="32"/><w:i/>')), styles=styles).paragraphs[0]
    assert para.dominant.size_pt == 16
    assert para.dominant.italic is True
    assert para.dominant.font == "Times New Roman"


def test_default_paragraph_style_applies_without_pstyle() -> None:
    styles = styles_xml(
        styles=style("Normal", default=True, ppr='<w:spacing w:line="360" w:lineRule="auto"/>')
    )
    para = model(p("metin"), styles=styles).paragraphs[0]
    assert para.style_id == "Normal"
    assert para.props.line_spacing == LineSpacing(LineRule.AUTO, 1.5)


def test_character_style_between_paragraph_style_and_direct() -> None:
    styles = styles_xml(
        defaults_rpr=TNR_12,
        styles=style("Normal", default=True) + style("Vurgu", "character", rpr="<w:b/>"),
    )
    para = model(p(r("x", rpr='<w:rStyle w:val="Vurgu"/>')), styles=styles).paragraphs[0]
    assert para.dominant.bold is True


def test_toggle_off_overrides_style() -> None:
    styles = styles_xml(styles=style("Normal", default=True, rpr="<w:b/>"))
    para = model(p(r("x", rpr='<w:b w:val="0"/>')), styles=styles).paragraphs[0]
    assert para.dominant.bold is False


def test_based_on_cycle_terminates() -> None:
    styles = styles_xml(
        styles=style("A", based_on="B", rpr='<w:sz w:val="20"/>')
        + style("B", based_on="A", rpr="<w:b/>")
    )
    para = model(p("x", ppr='<w:pStyle w:val="A"/>'), styles=styles).paragraphs[0]
    assert para.dominant.size_pt == 10


def test_theme_fonts() -> None:
    styles = styles_xml(defaults_rpr='<w:rFonts w:asciiTheme="minorHAnsi"/>')
    para = model(p("x"), styles=styles, theme=theme_xml("Cambria", "Calibri")).paragraphs[0]
    assert para.dominant.font == "Calibri"


def test_dominant_is_by_character_count() -> None:
    para = model(p(r("uzun kalın metin", rpr="<w:b/>"), r("kısa"))).paragraphs[0]
    assert para.dominant.bold is True


# --- Birimler ve bozuk değerler ----------------------------------------------------


def test_units() -> None:
    ppr = (
        '<w:ind w:left="567" w:hanging="567"/>'
        '<w:spacing w:before="240" w:after="120" w:line="240" w:lineRule="exact"/>'
    )
    props = model(p("x", ppr=ppr)).paragraphs[0].props
    assert props.indent_left_cm == pytest.approx(1.0, abs=0.01)
    assert props.first_line_cm == pytest.approx(-1.0, abs=0.01)
    assert props.space_before_pt == 12
    assert props.space_after_pt == 6
    assert props.line_spacing == LineSpacing(LineRule.EXACT, 12)


def test_malformed_values_are_ignored() -> None:
    ppr = '<w:ind w:left="abc"/><w:spacing w:line="çok"/><w:jc w:val="yamuk"/>'
    para = model(p(r("x", rpr='<w:sz w:val="NaN"/>'), ppr=ppr)).paragraphs[0]
    assert para.props.indent_left_cm is None
    assert para.props.line_spacing is None
    assert para.props.alignment is None
    assert para.dominant.size_pt is None


# --- Bölümler ----------------------------------------------------------------------


A4 = '<w:pgSz w:w="11906" w:h="16838"/>'


def test_sections_and_page_numbering() -> None:
    sect1 = (
        f'<w:sectPr>{A4}<w:pgMar w:top="1701" w:bottom="1418" w:left="1985" w:right="1418"/>'
        '<w:pgNumType w:fmt="lowerRoman" w:start="1"/></w:sectPr>'
    )
    body = (
        p("Özet")
        + p("Önsöz", ppr=sect1)
        + p("Giriş")
        + f'<w:sectPr>{A4}<w:pgMar w:top="2.5cm" w:bottom="1418" w:left="1985" w:right="1418"/>'
        '<w:pgNumType w:fmt="decimal" w:start="1"/><w:titlePg/></w:sectPr>'
    )
    doc = model(body)
    assert [s.index for s in doc.sections] == [0, 1]
    s0, s1 = doc.sections
    assert s0.page_width_cm == pytest.approx(21.0, abs=0.01)
    assert s0.page_height_cm == pytest.approx(29.7, abs=0.01)
    assert s0.margins.left_cm == pytest.approx(3.5, abs=0.01)
    assert s0.margins.top_cm == pytest.approx(3.0, abs=0.01)
    assert s0.page_number_format == "lowerRoman"
    assert s1.page_number_format == "decimal"
    assert s1.margins.top_cm == pytest.approx(2.5, abs=0.01)
    assert s1.title_page is True
    assert [para.section_index for para in doc.paragraphs] == [0, 0, 1]


def test_document_without_section_properties() -> None:
    doc = model(p("x"))
    assert len(doc.sections) == 1
    assert doc.sections[0].page_width_cm is None


# --- Yapı ----------------------------------------------------------------------------


def test_tables_and_nested_tables() -> None:
    inner = f"<w:tbl><w:tr><w:tc>{p('iç')}</w:tc></w:tr></w:tbl>"
    body = p("önce") + f"<w:tbl><w:tr><w:tc>{p('hücre')}{inner}</w:tc></w:tr></w:tbl>" + p("sonra")
    doc = model(body)
    assert [x.in_table for x in doc.paragraphs] == [False, True, True, False]
    assert [x.text for x in doc.paragraphs] == ["önce", "hücre", "iç", "sonra"]


def test_content_controls_are_walked() -> None:
    body = f"<w:sdt><w:sdtPr/><w:sdtContent>{p('İçindekiler')}</w:sdtContent></w:sdt>"
    assert model(body).paragraphs[0].text == "İçindekiler"


def test_numbering() -> None:
    ppr = '<w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr>'
    num = numbering_xml({0: ("decimal", "%1."), 1: ("decimal", "%1.%2.")})
    para = model(p("Alt başlık", ppr=ppr), numbering=num).paragraphs[0]
    assert para.numbering is not None
    assert para.numbering.level == 1
    assert para.numbering.num_format == "decimal"
    assert para.numbering.level_text == "%1.%2."


def test_num_id_zero_means_no_numbering() -> None:
    ppr = '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr>'
    assert model(p("x", ppr=ppr)).paragraphs[0].numbering is None


def test_footnotes_and_endnotes() -> None:
    doc = model(
        p("Gövde"),
        footnotes=notes_xml("footnote", {1: p("Dipnot")}),
        endnotes=notes_xml("endnote", {1: p("Sonnot")}),
    )
    stories = [(x.story, x.text) for x in doc.paragraphs]
    assert stories == [
        (Story.BODY, "Gövde"), (Story.FOOTNOTE, "Dipnot"), (Story.ENDNOTE, "Sonnot"),
    ]
    assert doc.paragraphs[1].section_index is None


def test_headers_footers_and_section_refs() -> None:
    sect = (
        '<w:sectPr><w:headerReference w:type="default" r:id="rIdH"/>'
        '<w:footerReference w:type="default" r:id="rIdF"/></w:sectPr>'
    )
    doc = model(
        p("Gövde") + sect,
        headers={"rIdH": hdr_xml(p("Üstbilgi"))},
        footers={"rIdF": hdr_xml(p("Altbilgi"), tag="ftr")},
    )
    assert doc.sections[0].headers == {"default": "word/header1.xml"}
    assert doc.sections[0].footers == {"default": "word/footer1.xml"}
    assert [(x.story, x.text) for x in doc.paragraphs][1:] == [
        (Story.HEADER, "Üstbilgi"), (Story.FOOTER, "Altbilgi"),
    ]


# --- Alanlar, değişiklik izleme, metin kutuları ------------------------------------


def test_complex_field_instruction_excluded_result_included() -> None:
    field = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> PAGE \\* roman </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + r("iv")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    para = model(p(r("Sayfa "), field)).paragraphs[0]
    assert para.text == "Sayfa iv"
    assert para.field_kinds == frozenset({"PAGE"})
    assert [run.field_kind for run in para.runs] == [None, "PAGE"]


def test_field_spanning_paragraphs() -> None:
    begin = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText> TOC \\o "1-3" </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    )
    end = '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    doc = model(p(begin, r("GİRİŞ\t1")) + p(r("YÖNTEM\t5"), end) + p("Normal"))
    assert [x.field_kinds for x in doc.paragraphs] == [
        frozenset({"TOC"}), frozenset({"TOC"}), frozenset(),
    ]


def test_simple_field() -> None:
    para = model(p(r("Şekil "), '<w:fldSimple w:instr=" SEQ Şekil \\* ARABIC ">'
                   + r("3") + "</w:fldSimple>")).paragraphs[0]
    assert para.text == "Şekil 3"
    assert "SEQ" in para.field_kinds


def test_tracked_changes() -> None:
    body = p(
        r("Kalan "),
        f'<w:ins w:id="1" w:author="x">{r("eklenen ")}</w:ins>',
        '<w:del w:id="2" w:author="x"><w:r><w:delText>silinen</w:delText></w:r></w:del>',
    )
    doc = model(body)
    assert doc.has_tracked_changes
    assert doc.paragraphs[0].text == "Kalan eklenen "
    assert [run.inserted for run in doc.paragraphs[0].runs] == [False, True]


def test_no_tracked_changes() -> None:
    assert not model(p("x")).has_tracked_changes


def test_textbox_once_and_separate() -> None:
    txbx = f"<w:txbxContent>{p('Kutu metni')}</w:txbxContent>"
    drawing = (
        "<w:r><mc:AlternateContent>"
        '<mc:Choice Requires="wps">'
        f"<w:drawing><wps:txbx>{txbx}</wps:txbx></w:drawing></mc:Choice>"
        f"<mc:Fallback><w:pict><v:textbox>{txbx}</v:textbox></w:pict></mc:Fallback>"
        "</mc:AlternateContent></w:r>"
    )
    doc = model(p(r("Dış "), drawing))
    assert [(x.text, x.in_textbox) for x in doc.paragraphs] == [
        ("Dış ", False), ("Kutu metni", True),
    ]


def test_special_characters() -> None:
    body = p('<w:r><w:t>a</w:t><w:tab/><w:t>b</w:t><w:br/><w:sym w:font="Symbol" w:char="03B1"/>'
             "<w:noBreakHyphen/></w:r>")
    assert model(body).paragraphs[0].text == "a\tb\nα‑"


def test_manual_page_break_flag() -> None:
    para = model(p('<w:r><w:br w:type="page"/></w:r>')).paragraphs[0]
    assert para.has_page_break


# --- Kimlikler ve gizlilik -----------------------------------------------------------


def test_para_ids() -> None:
    body = (
        p("a", attrs='w14:paraId="1A2B3C4D"')
        + p("b", attrs='w14:paraId="1A2B3C4D"')  # yinelenen
        + p("c", attrs='w14:paraId="kötü id"')
        + p("d")
    )
    ids = [x.para_id for x in model(body).paragraphs]
    assert ids[0] == "1A2B3C4D"
    assert len(set(ids)) == 4
    assert all(i.isascii() and " " not in i for i in ids)


def test_text_never_in_repr() -> None:
    doc = model(p(SECRET), footnotes=notes_xml("footnote", {1: p(SECRET)}))
    assert doc.paragraphs[0].text == SECRET
    assert SECRET not in repr(doc)
    assert SECRET not in str(doc.paragraphs)


def test_not_wordml() -> None:
    from builders import content_types, root_rels, zip_parts

    data = zip_parts({
        "[Content_Types].xml": content_types(),
        "_rels/.rels": root_rels(),
        "word/document.xml": b"<baska/>",
    })
    with pytest.raises(ParseError) as exc:
        parse_package(open_docx(data))
    assert exc.value.code is ErrorCode.NOT_WORDML
