from builders import hdr_xml, make_docx, notes_xml, p, r, style, styles_xml

from synora.fingerprint import content_fingerprint
from synora.ingest import open_docx


def fp(body: str, **kw: str | dict[str, str] | None) -> str:
    return content_fingerprint(open_docx(make_docx(body, **kw)))  # type: ignore[arg-type]


BASE = p("Birinci paragraf.") + p("İkinci paragraf.")


def test_stable() -> None:
    assert fp(BASE) == fp(BASE)
    assert len(fp(BASE)) == 64


def test_formatting_does_not_change_fingerprint() -> None:
    formatted = (
        p(r("Birinci paragraf.", rpr='<w:b/><w:sz w:val="28"/>'),
          ppr='<w:jc w:val="center"/><w:spacing w:line="360"/>')
        + p("İkinci paragraf.", ppr='<w:ind w:firstLine="709"/><w:pStyle w:val="Normal"/>')
    )
    styles = styles_xml(styles=style("Normal", default=True, rpr="<w:i/>"))
    assert fp(formatted, styles=styles) == fp(BASE)


def test_run_splitting_does_not_change_fingerprint() -> None:
    split = p(r("Birin"), r("ci para"), r("graf.")) + p("İkinci paragraf.")
    assert fp(split) == fp(BASE)


def test_section_and_page_settings_do_not_change_fingerprint() -> None:
    sect = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1701"/></w:sectPr>'
    assert fp(BASE + sect) == fp(BASE)


def test_field_instruction_change_does_not_change_fingerprint() -> None:
    def page_field(switch: str) -> str:
        return p(
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f"<w:r><w:instrText> PAGE {switch} </w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + r("1")
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        )
    assert fp(page_field("")) == fp(page_field("\\* roman"))


def test_single_character_change() -> None:
    assert fp(p("Birinci paragraf!") + p("İkinci paragraf.")) != fp(BASE)


def test_turkish_dotted_i_change() -> None:
    assert fp(p("Birinci paragraf.") + p("Ikinci paragraf.")) != fp(BASE)


def test_whitespace_change() -> None:
    assert fp(p("Birinci  paragraf.") + p("İkinci paragraf.")) != fp(BASE)


def test_tab_vs_space() -> None:
    tab = p('<w:r><w:t>Birinci</w:t><w:tab/><w:t>paragraf.</w:t></w:r>') + p("İkinci paragraf.")
    assert fp(tab) != fp(BASE)


def test_empty_paragraph_inserted() -> None:
    assert fp(p("Birinci paragraf.") + p("") + p("İkinci paragraf.")) != fp(BASE)


def test_paragraph_order() -> None:
    assert fp(p("İkinci paragraf.") + p("Birinci paragraf.")) != fp(BASE)


def test_paragraph_merge() -> None:
    assert fp(p("Birinci paragraf.İkinci paragraf.")) != fp(BASE)


def test_footnote_text_change() -> None:
    a = fp(BASE, footnotes=notes_xml("footnote", {1: p("Kaynak 2020.")}))
    b = fp(BASE, footnotes=notes_xml("footnote", {1: p("Kaynak 2021.")}))
    assert a != b


def test_header_text_change() -> None:
    a = fp(BASE, headers={"rIdH": hdr_xml(p("Tez Başlığı"))})
    b = fp(BASE, headers={"rIdH": hdr_xml(p("Tez Basligi"))})
    assert a != b


def test_field_result_change_is_detected() -> None:
    # Zotero/Mendeley atıfları alan sonucudur; metnin parçası sayılır.
    def cite(text: str) -> str:
        return p(
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            "<w:r><w:instrText> ADDIN ZOTERO_ITEM </w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + r(text)
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        )
    assert fp(cite("(Yılmaz, 2020)")) != fp(cite("(Yılmaz, 2021)"))


def test_textbox_text_change() -> None:
    def box(text: str) -> str:
        return p(f"<w:r><w:drawing><w:txbxContent>{p(text)}</w:txbxContent></w:drawing></w:r>")
    assert fp(box("Kutu A")) != fp(box("Kutu B"))


def test_inserted_text_counts_deleted_text_does_not() -> None:
    ins = p(r("Kalan "), f'<w:ins w:id="1" w:author="x">{r("eklenen")}</w:ins>')
    assert fp(ins) == fp(p("Kalan eklenen"))
    deleted = p(
        r("Kalan"),
        '<w:del w:id="1" w:author="x"><w:r><w:delText>x</w:delText></w:r></w:del>',
    )
    assert fp(deleted) == fp(p("Kalan"))
