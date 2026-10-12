"""A1: Kötü niyetli .docx girdileri doğru hata koduyla reddedilmeli."""

import zipfile

import pytest
from builders import (
    DOCM_MAIN,
    XLSX_MAIN,
    content_types,
    document_xml,
    minimal_parts,
    patch_zip,
    root_rels,
    zip_parts,
)

from synora.errors import ErrorCode, IngestError
from synora.ingest import Limits, open_docx


def reject(data: bytes, code: ErrorCode, limits: Limits | None = None) -> None:
    with pytest.raises(IngestError) as exc:
        open_docx(data, limits or Limits())
    assert exc.value.code is code


# --- Zip katmanı -----------------------------------------------------------------


def test_not_a_zip() -> None:
    reject(b"Bu bir zip degil", ErrorCode.NOT_A_ZIP)


def test_empty_input() -> None:
    reject(b"", ErrorCode.NOT_A_ZIP)


def test_file_too_large(valid_docx: bytes) -> None:
    reject(valid_docx, ErrorCode.FILE_TOO_LARGE, Limits(max_file_bytes=len(valid_docx) - 1))


def test_zip_bomb_compression_ratio() -> None:
    parts = minimal_parts()
    parts["word/media/bomb.bin"] = b"\0" * (4 * 1024 * 1024)
    reject(zip_parts(parts), ErrorCode.COMPRESSION_RATIO)


def test_total_uncompressed_too_large(valid_docx: bytes) -> None:
    reject(valid_docx, ErrorCode.TOTAL_TOO_LARGE, Limits(max_total_uncompressed=100))


def test_header_lies_about_size() -> None:
    # Başlık 10 bayt diyor, gerçekte ~100 KB. Ya okuma sırasında sayaç yakalar ya da
    # CRC uyuşmazlığı; her iki durumda da veri kabul edilmemeli.
    parts = minimal_parts()
    parts["word/media/big.bin"] = bytes(range(256)) * 400
    data = patch_zip(zip_parts(parts), "word/media/big.bin", file_size=10)
    with pytest.raises(IngestError) as exc:
        open_docx(data, Limits(max_total_uncompressed=50_000))
    assert exc.value.code in {ErrorCode.CORRUPT_ZIP, ErrorCode.TOTAL_TOO_LARGE}


def test_encrypted_entry(valid_docx: bytes) -> None:
    reject(patch_zip(valid_docx, "word/document.xml", flag_or=0x1), ErrorCode.ENCRYPTED)


def test_unsupported_compression() -> None:
    reject(zip_parts(minimal_parts(), compression=zipfile.ZIP_BZIP2),
           ErrorCode.UNSUPPORTED_COMPRESSION)


def test_too_many_parts() -> None:
    parts = minimal_parts()
    for i in range(10):
        parts[f"word/media/img{i}.bin"] = b"x"
    reject(zip_parts(parts), ErrorCode.TOO_MANY_PARTS, Limits(max_parts=5))


# Not: zipfile NUL sonrasını kendisi keser, Windows'ta "\" karakterini "/" yapar;
# bu yüzden o iki durum burada değil, _check_part_name birim testinde.
@pytest.mark.parametrize(
    "name",
    ["../evil.xml", "word/../../evil.xml", "/abs.xml", "C:/x.xml", "word//x.xml", "word/./x.xml"],
)
def test_bad_part_names(name: str) -> None:
    parts = [*list(minimal_parts().items()), (name, b"<a/>")]
    reject(zip_parts(parts), ErrorCode.BAD_PART_NAME)


def test_duplicate_part_names_case_insensitive() -> None:
    parts = [*list(minimal_parts().items()), ("WORD/document.xml", document_xml())]
    reject(zip_parts(parts), ErrorCode.DUPLICATE_PART)


def test_exact_duplicate_part_names() -> None:
    parts = [*list(minimal_parts().items()), ("word/document.xml", document_xml())]
    with pytest.warns(UserWarning):  # zipfile yinelenen adı uyarıyla yazar
        data = zip_parts(parts)
    reject(data, ErrorCode.DUPLICATE_PART)


# --- OPC paket katmanı -------------------------------------------------------------


def test_missing_content_types() -> None:
    parts = minimal_parts()
    del parts["[Content_Types].xml"]
    reject(zip_parts(parts), ErrorCode.MISSING_CONTENT_TYPES)


def test_missing_main_document_relationship() -> None:
    parts = minimal_parts()
    del parts["_rels/.rels"]
    reject(zip_parts(parts), ErrorCode.MISSING_MAIN_DOCUMENT)


def test_main_relationship_points_to_missing_part() -> None:
    parts = minimal_parts()
    parts["_rels/.rels"] = root_rels(target="word/yok.xml")
    reject(zip_parts(parts), ErrorCode.MISSING_MAIN_DOCUMENT)


def test_main_relationship_traversal() -> None:
    parts = minimal_parts()
    parts["_rels/.rels"] = root_rels(target="../../etc/passwd")
    reject(zip_parts(parts), ErrorCode.BAD_PART_NAME)


def test_macro_enabled_main_document() -> None:
    parts = minimal_parts()
    parts["[Content_Types].xml"] = content_types(main_type=DOCM_MAIN)
    reject(zip_parts(parts), ErrorCode.MACRO_ENABLED)


def test_vba_project_part() -> None:
    parts = minimal_parts()
    parts["word/vbaProject.bin"] = b"\xd0\xcf\x11\xe0"
    reject(zip_parts(parts), ErrorCode.MACRO_ENABLED)


def test_not_a_word_document() -> None:
    parts = minimal_parts()
    parts["[Content_Types].xml"] = content_types(main_type=XLSX_MAIN)
    reject(zip_parts(parts), ErrorCode.NOT_DOCX)


# --- XML katmanı (her XML part xmlsafe'den geçer) ----------------------------------


def test_xxe_in_document() -> None:
    parts = minimal_parts()
    parts["word/document.xml"] = (
        b'<?xml version="1.0"?><!DOCTYPE w [<!ENTITY x SYSTEM "file:///c:/windows/win.ini">]>'
        b"<w>&x;</w>"
    )
    reject(zip_parts(parts), ErrorCode.XML_DOCTYPE)


def test_doctype_in_secondary_part() -> None:
    parts = minimal_parts()
    parts["word/styles.xml"] = b'<!DOCTYPE s [<!ENTITY e "x">]><s>&e;</s>'
    reject(zip_parts(parts), ErrorCode.XML_DOCTYPE)


def test_doctype_in_rels() -> None:
    parts = minimal_parts()
    parts["_rels/.rels"] = b'<!DOCTYPE r [<!ENTITY e "x">]><r>&e;</r>'
    reject(zip_parts(parts), ErrorCode.XML_DOCTYPE)


def test_malformed_xml_part() -> None:
    parts = minimal_parts()
    parts["word/document.xml"] = b"<w:document><w:body>"
    reject(zip_parts(parts), ErrorCode.XML_MALFORMED)
