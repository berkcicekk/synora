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
