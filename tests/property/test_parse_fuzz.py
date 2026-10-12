"""A2: Ne kadar tuhaf biçim değeri gelirse gelsin parser çökmez."""

from builders import esc, make_docx, numbering_xml, p, r, style, styles_xml
from hypothesis import given, settings
from hypothesis import strategies as st

from synora.ingest import open_docx
from synora.parse import parse_package

VALUES = st.one_of(
    st.text(st.characters(codec="ascii", categories=("L", "N", "P")), max_size=12),
    st.integers(-(10**12), 10**12).map(str),
    st.sampled_from(["", "-0", "1e9", "2.5cm", "99999999999999999999", "auto", "none", "0"]),
)
PPR_TAGS = [("jc", "val"), ("ind", "left"), ("ind", "hanging"), ("ind", "firstLine"),
            ("spacing", "line"), ("spacing", "lineRule"), ("spacing", "before"),
            ("outlineLvl", "val"), ("pStyle", "val")]
RPR_TAGS = [("sz", "val"), ("b", "val"), ("u", "val"), ("rFonts", "asciiTheme"),
            ("rStyle", "val"), ("vertAlign", "val"), ("sym", "char")]


def attrs(tags: list[tuple[str, str]]) -> st.SearchStrategy[str]:
    item = st.tuples(st.sampled_from(tags), VALUES).map(
        lambda t: f'<w:{t[0][0]} w:{t[0][1]}="{esc(t[1]).replace(chr(34), "")}"/>'
    )
    return st.lists(item, max_size=5).map("".join)


@settings(max_examples=200, deadline=None)
@given(attrs(PPR_TAGS), attrs(RPR_TAGS), VALUES, VALUES)
def test_garbage_properties_never_crash(ppr: str, rpr: str, num_id: str, based: str) -> None:
    clean = lambda s: esc(s).replace('"', "")  # noqa: E731
    numpr = f'<w:numPr><w:ilvl w:val="{clean(based)}"/><w:numId w:val="{clean(num_id)}"/></w:numPr>'
    styles = styles_xml(
        defaults_rpr=rpr,
        styles=style("A", based_on=clean(based) or None, ppr=ppr, rpr=rpr)
        + style(clean(based) or "B", based_on="A"),
    )
    sect = (
        f'<w:sectPr><w:pgSz w:w="{clean(num_id)}"/>'
        f'<w:pgNumType w:start="{clean(based)}"/></w:sectPr>'
    )
    body = p(r("x", rpr=rpr), ppr=ppr + numpr + '<w:pStyle w:val="A"/>') + sect
    data = make_docx(body, styles=styles, numbering=numbering_xml({0: ("decimal", "%1.")}))
    parse_package(open_docx(data))
