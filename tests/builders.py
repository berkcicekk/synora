"""Testler için sentetik .docx üreticileri. Gerçek tez içeriği kullanılmaz."""

from __future__ import annotations

import io
import struct
import zipfile

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DOCX_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
DOCM_MAIN = "application/vnd.ms-word.document.macroEnabled.main+xml"
XLSX_MAIN = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
OFFICE_DOC_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
HYPERLINK_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"


def content_types(main_type: str = DOCX_MAIN, extra_overrides: str = "") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/word/document.xml" ContentType="{main_type}"/>'
        f"{extra_overrides}"
        "</Types>"
    ).encode()


def root_rels(target: str = "word/document.xml") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{OFFICE_DOC_REL}" Target="{target}"/>'
        "</Relationships>"
    ).encode()


def document_xml(paragraphs: tuple[str, ...] = ("Sentetik paragraf.",)) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
    ).encode()


def minimal_parts() -> dict[str, bytes]:
    return {
        "[Content_Types].xml": content_types(),
        "_rels/.rels": root_rels(),
        "word/document.xml": document_xml(),
    }


def zip_parts(
    parts: dict[str, bytes] | list[tuple[str, bytes]],
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    items = parts.items() if isinstance(parts, dict) else parts
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=compression) as zf:
        for name, data in items:
            info = zipfile.ZipInfo(name)
            info.compress_type = compression
            zf.writestr(info, data)
    return buf.getvalue()


def minimal_docx() -> bytes:
    return zip_parts(minimal_parts())


# --- Zengin belge üretici (F1+) ----------------------------------------------------

NS_DECL = (
    f'xmlns:w="{W_NS}" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
)
REL_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def r(text: str, rpr: str = "") -> str:
    rpr_xml = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    return f'<w:r>{rpr_xml}<w:t xml:space="preserve">{esc(text)}</w:t></w:r>'


def p(*runs: str, ppr: str = "", attrs: str = "") -> str:
    """runs: r() çıktıları ya da düz metin (tek run'a çevrilir)."""
    body = "".join(x if x.startswith("<") else r(x) for x in runs)
    ppr_xml = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
    return f"<w:p {attrs}>{ppr_xml}{body}</w:p>"


def styles_xml(defaults_rpr: str = "", defaults_ppr: str = "", styles: str = "") -> str:
    return (
        f"{XML_DECL}<w:styles {NS_DECL}><w:docDefaults>"
        f"<w:rPrDefault><w:rPr>{defaults_rpr}</w:rPr></w:rPrDefault>"
        f"<w:pPrDefault><w:pPr>{defaults_ppr}</w:pPr></w:pPrDefault>"
        f"</w:docDefaults>{styles}</w:styles>"
    )


def style(sid: str, kind: str = "paragraph", *, based_on: str | None = None,
          ppr: str = "", rpr: str = "", default: bool = False, name: str | None = None) -> str:
    d = ' w:default="1"' if default else ""
    b = f'<w:basedOn w:val="{based_on}"/>' if based_on else ""
    return (
        f'<w:style w:type="{kind}" w:styleId="{sid}"{d}><w:name w:val="{name or sid}"/>{b}'
        f"<w:pPr>{ppr}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>"
    )


def theme_xml(major: str, minor: str) -> str:
    return (
        f'{XML_DECL}<a:theme {NS_DECL} name="T"><a:themeElements><a:fontScheme name="F">'
        f'<a:majorFont><a:latin typeface="{major}"/></a:majorFont>'
        f'<a:minorFont><a:latin typeface="{minor}"/></a:minorFont>'
        "</a:fontScheme></a:themeElements></a:theme>"
    )


def numbering_xml(levels: dict[int, tuple[str, str]], num_id: int = 1) -> str:
    lvls = "".join(
        f'<w:lvl w:ilvl="{i}"><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/></w:lvl>'
        for i, (fmt, text) in levels.items()
    )
    return (
        f'{XML_DECL}<w:numbering {NS_DECL}><w:abstractNum w:abstractNumId="7">{lvls}'
        f'</w:abstractNum><w:num w:numId="{num_id}"><w:abstractNumId w:val="7"/></w:num>'
        "</w:numbering>"
    )


def notes_xml(kind: str, notes: dict[int, str]) -> str:
    """kind: footnote/endnote. notes: id → içerik (p() çıktıları)."""
    sep = (
        f'<w:{kind} w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:{kind}>'
    )
    body = "".join(f'<w:{kind} w:id="{i}">{xml}</w:{kind}>' for i, xml in notes.items())
    return f"{XML_DECL}<w:{kind}s {NS_DECL}>{sep}{body}</w:{kind}s>"


def hdr_xml(content: str, tag: str = "hdr") -> str:
    return f"{XML_DECL}<w:{tag} {NS_DECL}>{content}</w:{tag}>"


def make_docx(
    body: str,
    *,
    styles: str | None = None,
    numbering: str | None = None,
    theme: str | None = None,
    footnotes: str | None = None,
    endnotes: str | None = None,
    headers: dict[str, str] | None = None,
    footers: dict[str, str] | None = None,
) -> bytes:
    """body: <w:body> içeriği. headers/footers: rId → hdr_xml() çıktısı."""
    parts: dict[str, bytes] = {
        "_rels/.rels": root_rels(),
        "word/document.xml": f"{XML_DECL}<w:document {NS_DECL}><w:body>{body}</w:body>"
        "</w:document>".encode(),
    }
    rels: list[tuple[str, str, str]] = []
    overrides: list[tuple[str, str]] = []
    ct_base = "application/vnd.openxmlformats-officedocument.wordprocessingml."
    for content, rel, name, ctype in (
        (styles, "styles", "styles.xml", "styles+xml"),
        (numbering, "numbering", "numbering.xml", "numbering+xml"),
        (theme, "theme", "theme/theme1.xml", None),
        (footnotes, "footnotes", "footnotes.xml", "footnotes+xml"),
        (endnotes, "endnotes", "endnotes.xml", "endnotes+xml"),
    ):
        if content is not None:
            parts[f"word/{name}"] = content.encode()
            rels.append((f"rId{rel}", REL_BASE + rel, name))
            if ctype:
                overrides.append((f"/word/{name}", ct_base + ctype))
    for kind, mapping in (("header", headers or {}), ("footer", footers or {})):
        for i, (rid, content) in enumerate(mapping.items(), start=1):
            name = f"{kind}{i}.xml"
            parts[f"word/{name}"] = content.encode()
            rels.append((rid, REL_BASE + kind, name))
            overrides.append((f"/word/{name}", ct_base + kind + "+xml"))
    if rels:
        parts["word/_rels/document.xml.rels"] = (
            f'{XML_DECL}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            'relationships">'
            + "".join(f'<Relationship Id="{i}" Type="{t}" Target="{n}"/>' for i, t, n in rels)
            + "</Relationships>"
        ).encode()
    extra = "".join(f'<Override PartName="{n}" ContentType="{c}"/>' for n, c in overrides)
    parts["[Content_Types].xml"] = content_types(extra_overrides=extra)
    return zip_parts(parts)


def _central_entries(data: bytes) -> list[tuple[int, str]]:
    """Merkezi dizindeki (kayıt ofseti, ad) çiftleri."""
    out: list[tuple[int, str]] = []
    pos = data.find(b"PK\x01\x02")
    while pos != -1:
        name_len, extra_len, comment_len = struct.unpack_from("<HHH", data, pos + 28)
        name = data[pos + 46 : pos + 46 + name_len].decode("utf-8")
        out.append((pos, name))
        pos = data.find(b"PK\x01\x02", pos + 46 + name_len + extra_len + comment_len)
    return out


def patch_zip(data: bytes, name: str, *, file_size: int | None = None, flag_or: int = 0) -> bytes:
    """Zip başlıklarını (yerel + merkezi) elle bozar: boyut yalanı, şifre bayrağı vb."""
    buf = bytearray(data)
    for central, entry_name in _central_entries(data):
        if entry_name != name:
            continue
        (local,) = struct.unpack_from("<I", buf, central + 42)
        if file_size is not None:
            struct.pack_into("<I", buf, central + 24, file_size)
            struct.pack_into("<I", buf, local + 22, file_size)
        if flag_or:
            (cflags,) = struct.unpack_from("<H", buf, central + 8)
            struct.pack_into("<H", buf, central + 8, cflags | flag_or)
            (lflags,) = struct.unpack_from("<H", buf, local + 6)
            struct.pack_into("<H", buf, local + 6, lflags | flag_or)
        return bytes(buf)
    raise KeyError(name)
