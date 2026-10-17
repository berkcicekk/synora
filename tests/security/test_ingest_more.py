"""A1 ek saldırılar (gece taraması): kodlama hileleri, iç içe zip, derin XML, şablon/makro türleri.

Mevcut test_ingest_attacks.py'yi tamamlar; A1 kodu değiştirilmedi.
"""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pytest
from builders import DOCX_MAIN, content_types, document_xml, minimal_parts, zip_parts

from synora.errors import ErrorCode, IngestError, SynoraError
from synora.ingest import Limits, open_docx

DOTX_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"
DOTM_MAIN = "application/vnd.ms-word.template.macroEnabledTemplate.main+xml"


def code_of(data: bytes, limits: Limits | None = None) -> ErrorCode:
    with pytest.raises(SynoraError) as exc:
        open_docx(data, limits or Limits())
    return exc.value.code


def with_document(xml: bytes) -> bytes:
    parts = minimal_parts()
    parts["word/document.xml"] = xml
    return zip_parts(parts)


# --- XML kodlama hileleri: DOCTYPE bayt deseniyle aranır; başka kodlamalar ikinci kapıya ---


@pytest.mark.parametrize("encoding", ["utf-7", "cp037"])  # cp037 = EBCDIC
def test_doctype_hidden_by_exotic_encoding_is_rejected(encoding: str) -> None:
    xml = (f'<?xml version="1.0" encoding="{encoding}"?>'
           '<!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]><d>&x;</d>')
    data = with_document(xml.encode(encoding))
    assert code_of(data) in (ErrorCode.XML_DOCTYPE, ErrorCode.XML_MALFORMED)


def test_utf16_with_bom_doctype_is_rejected() -> None:
    xml = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE d [<!ENTITY a "b">]><d>&a;</d>'
    assert code_of(with_document(xml.encode("utf-16"))) is ErrorCode.XML_DOCTYPE


def test_parameter_entity_is_rejected() -> None:
    xml = (b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY % p SYSTEM "http://198.51.100.1/x.dtd">'
           b"%p;]><d/>")
    assert code_of(with_document(xml)) is ErrorCode.XML_DOCTYPE


def test_xinclude_is_not_processed() -> None:
    # XInclude yalnızca açıkça çağrılırsa işlenir; xmlsafe bunu yapmaz → belge sıradan öğe içerir.
    xml = (b'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           b'wordprocessingml/2006/main" xmlns:xi="http://www.w3.org/2001/XInclude"><w:body>'
           b'<xi:include href="file:///etc/passwd" parse="text"/></w:body></w:document>')
    pkg = open_docx(with_document(xml))
    assert b"xi:include" in pkg.parts["word/document.xml"]
    assert b"root:" not in pkg.parts["word/document.xml"]


# --- XML boyut ve derinlik ----------------------------------------------------------------------


def test_deeply_nested_xml_is_rejected_quickly() -> None:
    depth = 5000  # libxml2 huge_tree kapalıyken derinlik sınırı 256
    xml = b"<?xml version='1.0'?>" + b"<a>" * depth + b"</a>" * depth
    start = time.monotonic()
    assert code_of(with_document(xml)) is ErrorCode.XML_MALFORMED
    assert time.monotonic() - start < 5


def test_huge_text_node_is_bounded_by_xml_byte_limit() -> None:
    # Not: libxml2 2.11 bu düğümü huge_tree kapalıyken de kabul ediyor; tek düğüm sınırına
    # güvenilmez. Belleği sınırlayan kapı part başına bayt sınırıdır (varsayılan 64 MB).
    big = b"A" * (11 * 1024 * 1024)
    xml = (b'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           b'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + big
           + b"</w:t></w:r></w:p></w:body></w:document>")
    limits = Limits(ratio_min_bytes=64 * 1024 * 1024, max_xml_bytes=8 * 1024 * 1024)
    assert code_of(with_document(xml), limits) is ErrorCode.XML_TOO_LARGE


def test_xml_part_over_byte_limit() -> None:
    limits = Limits(max_xml_bytes=1024)
    big = document_xml(("x" * 2000,))
    assert code_of(with_document(big), limits) is ErrorCode.XML_TOO_LARGE


# --- Zip katmanı ------------------------------------------------------------------------------


def _inner_bomb(size: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.bin", b"\0" * size)
    return buf.getvalue()


def test_nested_zip_is_never_expanded() -> None:
    # Gömülü nesne olarak iç zip: Synora içini açmaz; yalnızca kendi baytları sayılır.
    inner = _inner_bomb(50 * 1024 * 1024)  # 50 MB sıfır → ~50 KB
    parts = minimal_parts()
    parts["word/embeddings/oleObject1.bin"] = inner
    pkg = open_docx(zip_parts(parts, compression=zipfile.ZIP_STORED))
    assert len(pkg.parts["word/embeddings/oleObject1.bin"]) == len(inner)
    assert len(inner) < 1024 * 1024


def test_many_small_highly_compressed_parts_hit_total_limit() -> None:
    # Her parça oran eşiğinin (1 MB) altında; toplam sınır yine de devreye girer.
    parts = minimal_parts()
    for i in range(12):
        parts[f"word/media/z{i}.bin"] = b"\0" * (900 * 1024)
    limits = Limits(max_total_uncompressed=8 * 1024 * 1024)
    assert code_of(zip_parts(parts), limits) is ErrorCode.TOTAL_TOO_LARGE


def test_truncated_docx() -> None:
    data = zip_parts(minimal_parts())
    assert code_of(data[: len(data) - 30]) in (ErrorCode.NOT_A_ZIP, ErrorCode.CORRUPT_ZIP)


@pytest.mark.parametrize("name", ["C:/x.xml", "word\\..\\x.xml", "/etc/passwd", "word/\x01.xml",
                                  "word/./x.xml", "word//x.xml"])
def test_hostile_part_names(name: str) -> None:
    parts = [*minimal_parts().items(), (name, b"<x/>")]
    with pytest.raises(IngestError) as exc:
        open_docx(zip_parts(parts))
    assert exc.value.code in (ErrorCode.BAD_PART_NAME, ErrorCode.NOT_A_ZIP)


def test_nul_in_part_name_cannot_smuggle_a_second_name() -> None:
    # Python zipfile adı NUL'da keser ("word/doc"); kesilen ad başka bir parçayı ezemez.
    parts = list(minimal_parts().items()) + [("word/document.xml\x00.png", b"<x/>")]
    with pytest.raises(IngestError) as exc:
        open_docx(zip_parts(parts))
    assert exc.value.code is ErrorCode.DUPLICATE_PART


def test_exe_disguised_as_docx() -> None:
    assert code_of(b"MZ\x90\x00" + b"\0" * 2000) is ErrorCode.NOT_A_ZIP


def test_pdf_disguised_as_docx() -> None:
    assert code_of(b"%PDF-1.7\n" + b"\0" * 2000) is ErrorCode.NOT_A_ZIP


# --- Belge türü sahteciliği ----------------------------------------------------------------------


def test_macro_template_is_rejected() -> None:
    parts = minimal_parts()
    parts["[Content_Types].xml"] = content_types(main_type=DOTM_MAIN)
    assert code_of(zip_parts(parts)) is ErrorCode.MACRO_ENABLED


def test_plain_template_is_not_a_document() -> None:
    parts = minimal_parts()
    parts["[Content_Types].xml"] = content_types(main_type=DOTX_MAIN)
    assert code_of(zip_parts(parts)) is ErrorCode.NOT_DOCX


@pytest.mark.parametrize("name", ["Word/VBAPROJECT.BIN", "customXml/vbaProject.bin"])
def test_vba_project_anywhere_any_case(name: str) -> None:
    parts = minimal_parts()
    parts[name] = b"\xd0\xcf\x11\xe0"
    assert code_of(zip_parts(parts)) is ErrorCode.MACRO_ENABLED


def test_macro_content_type_on_side_part() -> None:
    extra = ('<Override PartName="/word/x.bin" '
             'ContentType="application/vnd.ms-office.vbaProject"/>')
    parts = minimal_parts()
    parts["[Content_Types].xml"] = content_types(DOCX_MAIN, extra)
    parts["word/x.bin"] = b"\xd0\xcf\x11\xe0"
    assert code_of(zip_parts(parts)) is ErrorCode.MACRO_ENABLED


def test_error_never_contains_document_text() -> None:
    secret = "GIZLI-TEZ-CUMLESI"
    xml = f'<?xml version="1.0"?><w:document><w:body><w:p>{secret}</w:body>'.encode()
    with pytest.raises(SynoraError) as exc:
        open_docx(with_document(xml))
    assert secret not in str(exc.value) and secret not in repr(exc.value)
    # lxml'in mesajı belge parçası içerebilir: zincir gösterilmemeli (raise ... from None).
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None or exc.value.__suppress_context__


# --- Mimari §8: altChunk ve gömülü OLE "dokunulmaz, uyarı bulgusu üretilir" ----------------------


@pytest.mark.xfail(strict=True, reason=(
    "Mimari §8 altChunk/gömülü OLE için uyarı bulgusu istiyor; denetim (A6) bunu üretmiyor. "
    "altChunk içeriği (başka bir belge) denetlenmediği gibi kullanıcıya da söylenmiyor. "
    "Öneri: ONERILER Ö4."))
def test_alt_chunk_produces_warning() -> None:
    import json

    from thesis import front_matter, main_matter, thesis

    from synora.web.pipeline import run_pipeline

    data = thesis(front_matter() + main_matter(extra='<w:altChunk r:id="rId99"/>'))
    ruleset = Path(__file__).resolve().parents[2] / "rulesets" / "example.yaml"
    result = run_pipeline(data, str(ruleset), "job")
    report = json.loads(result["report"] or "{}")
    assert any(f["severity"] == "warning" and "chunk" in f["rule_id"].lower()
               for f in report["findings"])
