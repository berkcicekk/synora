"""A1 — Güvenli giriş.

Her .docx saldırgan olabilir varsayımıyla zip ve OPC paket katmanını doğrular,
sınırları uygular ve doğrulanmış parçaları değiştirilemez bir pakette döndürür.
Harici ilişkiler yalnızca kaydedilir, asla takip edilmez.
"""

from __future__ import annotations

import hashlib
import io
import posixpath
import struct
import zipfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from synora import xmlsafe
from synora.errors import ErrorCode, IngestError

MB = 1024 * 1024

DOCX_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
MACRO_CONTENT_TYPES = frozenset(
    {
        "application/vnd.ms-word.document.macroenabled.main+xml",
        "application/vnd.ms-word.template.macroenabledtemplate.main+xml",
        "application/vnd.ms-office.vbaproject",
    }
)
CONTENT_TYPES_PART = "[Content_Types].xml"
ROOT_RELS_PART = "_rels/.rels"
_CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_OFFICE_DOC_REL_SUFFIX = "/officeDocument"

_ZIP_OPEN_ERRORS = (
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    ValueError,
    OSError,
    EOFError,
    struct.error,
    NotImplementedError,
    UnicodeDecodeError,
)
_ZIP_READ_ERRORS = (*_ZIP_OPEN_ERRORS, zlib.error, KeyError, RuntimeError)
_CHUNK = 64 * 1024


@dataclass(frozen=True, slots=True)
class Limits:
    max_file_bytes: int = 50 * MB
    max_total_uncompressed: int = 300 * MB
    max_parts: int = 2000
    max_ratio: int = 100
    # Oran denetimi bu boyutun üzerindeki parçalara uygulanır; küçük ve tekrarlı
    # XML parçaları meşru olarak yüksek oranla sıkışabilir.
    ratio_min_bytes: int = 1 * MB
    max_xml_bytes: int = xmlsafe.DEFAULT_MAX_BYTES


@dataclass(frozen=True, slots=True)
class ExternalRelationship:
    """Harici bir ilişki. Hedef adres belge içeriği sayılır ve tutulmaz."""

    rels_part: str
    rel_id: str
    rel_type: str


@dataclass(frozen=True, slots=True)
class DocxPackage:
    parts: Mapping[str, bytes]
    content_types: Mapping[str, str]
    main_part: str
    external_relationships: tuple[ExternalRelationship, ...]
    sha256: str


def open_docx(data: bytes, limits: Limits | None = None) -> DocxPackage:
    limits = limits or Limits()
    if len(data) > limits.max_file_bytes:
        raise IngestError(ErrorCode.FILE_TOO_LARGE)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except _ZIP_OPEN_ERRORS:
        raise IngestError(ErrorCode.NOT_A_ZIP) from None
    with zf:
        infos = _validate_entries(zf.infolist(), limits)
        parts = _read_entries(zf, infos, limits)

    by_fold = {name.casefold(): name for name in parts}
    ct_name = by_fold.get(CONTENT_TYPES_PART.casefold())
    if ct_name is None:
        raise IngestError(ErrorCode.MISSING_CONTENT_TYPES)

    for name, blob in parts.items():
        if _is_xml_part(name):
            xmlsafe.parse(blob, max_bytes=limits.max_xml_bytes)

    content_types = _resolve_content_types(parts, ct_name)
    _reject_macros(parts, content_types)
    main_part = _find_main_part(parts, by_fold)
    main_type = content_types.get(main_part, "")
    if main_type in MACRO_CONTENT_TYPES:
        raise IngestError(ErrorCode.MACRO_ENABLED)
    if main_type != DOCX_MAIN.casefold():
        raise IngestError(ErrorCode.NOT_DOCX)

    return DocxPackage(
        parts=MappingProxyType(parts),
        content_types=MappingProxyType(content_types),
        main_part=main_part,
        external_relationships=_external_relationships(parts),
        sha256=hashlib.sha256(data).hexdigest(),
    )


# --- Zip katmanı -------------------------------------------------------------------


def _check_part_name(name: str) -> None:
    if (
        not name
        or name.startswith("/")
        or any(c in name for c in "\\:")
        or any(ord(c) < 0x20 for c in name)
    ):
        raise IngestError(ErrorCode.BAD_PART_NAME)
    segments = name.removesuffix("/").split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        raise IngestError(ErrorCode.BAD_PART_NAME)


def _validate_entries(infos: list[zipfile.ZipInfo], limits: Limits) -> list[zipfile.ZipInfo]:
    if len(infos) > limits.max_parts:
        raise IngestError(ErrorCode.TOO_MANY_PARTS)
    seen: set[str] = set()
    files: list[zipfile.ZipInfo] = []
    declared_total = 0
    for info in infos:
        _check_part_name(info.filename)
        if info.flag_bits & 0x1:
            raise IngestError(ErrorCode.ENCRYPTED)
        folded = info.filename.casefold()
        if folded in seen:
            raise IngestError(ErrorCode.DUPLICATE_PART)
        seen.add(folded)
        if info.is_dir():
            continue
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise IngestError(ErrorCode.UNSUPPORTED_COMPRESSION)
        declared_total += info.file_size
        if declared_total > limits.max_total_uncompressed:
            raise IngestError(ErrorCode.TOTAL_TOO_LARGE)
        files.append(info)
    return files


def _read_entries(
    zf: zipfile.ZipFile, infos: list[zipfile.ZipInfo], limits: Limits
) -> dict[str, bytes]:
    """Parçaları okurken boyutu gerçekten sayar: zip başlığındaki boyuta güvenilmez."""
    parts: dict[str, bytes] = {}
    total = 0
    for info in infos:
        ratio_cap = max(limits.ratio_min_bytes, limits.max_ratio * max(info.compress_size, 1))
        chunks: list[bytes] = []
        size = 0
        try:
            with zf.open(info) as fh:
                while chunk := fh.read(_CHUNK):
                    size += len(chunk)
                    total += len(chunk)
                    if total > limits.max_total_uncompressed:
                        raise IngestError(ErrorCode.TOTAL_TOO_LARGE)
                    if size > ratio_cap:
                        raise IngestError(ErrorCode.COMPRESSION_RATIO)
                    chunks.append(chunk)
        except IngestError:
            raise
        except _ZIP_READ_ERRORS:
            raise IngestError(ErrorCode.CORRUPT_ZIP) from None
        parts[info.filename] = b"".join(chunks)
    return parts


# --- OPC paket katmanı ---------------------------------------------------------------


def _is_xml_part(name: str) -> bool:
    folded = name.casefold()
    return folded.endswith((".xml", ".rels"))


def _resolve_content_types(parts: Mapping[str, bytes], ct_name: str) -> dict[str, str]:
    root = xmlsafe.parse(parts[ct_name])
    defaults: dict[str, str] = {}
    overrides: dict[str, str] = {}
    for el in root.iter(f"{_CT_NS}Default"):
        ext, ctype = el.get("Extension"), el.get("ContentType")
        if ext and ctype:
            defaults[ext.casefold()] = ctype.casefold()
    for el in root.iter(f"{_CT_NS}Override"):
        name, ctype = el.get("PartName"), el.get("ContentType")
        if name and ctype:
            overrides[name.lstrip("/").casefold()] = ctype.casefold()
    resolved: dict[str, str] = {}
    for name in parts:
        folded = name.casefold()
        ext = posixpath.splitext(folded)[1].lstrip(".")
        ctype = overrides.get(folded) or defaults.get(ext)
        if ctype:
            resolved[name] = ctype
    return resolved


def _reject_macros(parts: Mapping[str, bytes], content_types: Mapping[str, str]) -> None:
    for name in parts:
        if posixpath.basename(name.casefold()) == "vbaproject.bin":
            raise IngestError(ErrorCode.MACRO_ENABLED)
    if any(ct in MACRO_CONTENT_TYPES for ct in content_types.values()):
        raise IngestError(ErrorCode.MACRO_ENABLED)


def _find_main_part(parts: Mapping[str, bytes], by_fold: Mapping[str, str]) -> str:
    rels_name = by_fold.get(ROOT_RELS_PART.casefold())
    if rels_name is None:
        raise IngestError(ErrorCode.MISSING_MAIN_DOCUMENT)
    root = xmlsafe.parse(parts[rels_name])
    for rel in root.iter(f"{_REL_NS}Relationship"):
        rel_type = rel.get("Type") or ""
        if not rel_type.endswith(_OFFICE_DOC_REL_SUFFIX) or rel.get("TargetMode") == "External":
            continue
        target = (rel.get("Target") or "").lstrip("/")
        _check_part_name(target)
        normalized = posixpath.normpath(target)
        if normalized != target:
            raise IngestError(ErrorCode.BAD_PART_NAME)
        actual = by_fold.get(target.casefold())
        if actual is None:
            raise IngestError(ErrorCode.MISSING_MAIN_DOCUMENT)
        return actual
    raise IngestError(ErrorCode.MISSING_MAIN_DOCUMENT)


def _external_relationships(parts: Mapping[str, bytes]) -> tuple[ExternalRelationship, ...]:
    found: list[ExternalRelationship] = []
    for name, blob in parts.items():
        if not name.casefold().endswith(".rels"):
            continue
        root = xmlsafe.parse(blob)
        for rel in root.iter(f"{_REL_NS}Relationship"):
            if rel.get("TargetMode") == "External":
                found.append(
                    ExternalRelationship(
                        rels_part=name, rel_id=rel.get("Id") or "", rel_type=rel.get("Type") or ""
                    )
                )
    return tuple(found)
