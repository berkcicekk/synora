"""rulesets/example.yaml'a tam uyan sentetik bir tez ve onu bozmak için parçalar."""

from __future__ import annotations

from builders import make_docx, notes_xml, p, r, style, styles_xml

TNR = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>'
NO_INDENT = '<w:ind w:firstLine="0"/>'

STYLES = styles_xml(
    defaults_rpr=TNR + '<w:sz w:val="24"/>',
    styles=(
        style("Normal", default=True, name="Normal",
              ppr='<w:jc w:val="both"/><w:spacing w:before="0" w:after="120" w:line="360" '
                  'w:lineRule="auto"/><w:ind w:firstLine="709"/>')
        + style("Heading1", based_on="Normal", name="heading 1",
                ppr='<w:jc w:val="center"/><w:pageBreakBefore/><w:spacing w:after="240"/>'
                    + NO_INDENT,
                rpr='<w:b/><w:caps/><w:sz w:val="28"/>')
        + style("Heading2", based_on="Normal", name="heading 2",
                ppr='<w:jc w:val="left"/>' + NO_INDENT, rpr="<w:b/>")
        + style("Caption", based_on="Normal", name="caption",
                ppr='<w:jc w:val="center"/>' + NO_INDENT, rpr='<w:sz w:val="20"/>')
        + style("FootnoteText", based_on="Normal", name="footnote text",
                ppr='<w:spacing w:line="240" w:after="0"/>' + NO_INDENT,
                rpr='<w:sz w:val="20"/>')
    ),
)

A4 = '<w:pgSz w:w="11906" w:h="16838"/>'
MARGINS = '<w:pgMar w:top="1701" w:bottom="1417" w:left="1985" w:right="1417"/>'


def sect(fmt: str, *, page: str = A4, margins: str = MARGINS) -> str:
    # start="1": biçim değişen bölümde numara 1'den başlar (page_numbering.restart kuralı).
    return f'<w:sectPr>{page}{margins}<w:pgNumType w:fmt="{fmt}" w:start="1"/></w:sectPr>'


def h1(text: str) -> str:
    return p(text, ppr='<w:pStyle w:val="Heading1"/>')


def h2(text: str) -> str:
    return p(text, ppr='<w:pStyle w:val="Heading2"/>')


def caption(text: str, ppr: str = "") -> str:
    return p(text, ppr='<w:pStyle w:val="Caption"/>' + ppr)


BODY_TEXT = "Bu paragraf sentetik bir gövde metnidir ve tezin herhangi bir bölümünü temsil eder."


def table() -> str:
    cell = p("Hücre", ppr=NO_INDENT + '<w:jc w:val="left"/><w:spacing w:line="240"/>')
    return f"<w:tbl><w:tr><w:tc>{cell}</w:tc></w:tr></w:tbl>"


def front_matter() -> str:
    return h1("ÖNSÖZ") + p(BODY_TEXT, ppr=f"{sect('lowerRoman')}")


def main_matter(extra: str = "") -> str:
    return (
        h1("GİRİŞ")
        + p(BODY_TEXT)
        + h2("1.1 Amaç")
        + p(r(BODY_TEXT), '<w:r><w:footnoteReference w:id="1"/></w:r>')
        + caption("Şekil 1.1 Örnek şekil")
        + caption("Tablo 1.1 Örnek tablo", ppr='<w:jc w:val="left"/>')
        + table()
        + p("")
        + extra
        + sect("decimal")
    )


FOOTNOTES = notes_xml("footnote", {1: p("Dipnot metni.", ppr='<w:pStyle w:val="FootnoteText"/>')})


def thesis(body: str | None = None, *, styles: str = STYLES) -> bytes:
    return make_docx(body if body is not None else front_matter() + main_matter(),
                     styles=styles, footnotes=FOOTNOTES)
