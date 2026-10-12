"""Hata tipleri. Hatalar yalnızca kod taşır; belge içeriği asla mesaja girmez."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    # Zip katmanı
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    NOT_A_ZIP = "NOT_A_ZIP"
    CORRUPT_ZIP = "CORRUPT_ZIP"
    ENCRYPTED = "ENCRYPTED"
    UNSUPPORTED_COMPRESSION = "UNSUPPORTED_COMPRESSION"
    TOO_MANY_PARTS = "TOO_MANY_PARTS"
    BAD_PART_NAME = "BAD_PART_NAME"
    DUPLICATE_PART = "DUPLICATE_PART"
    TOTAL_TOO_LARGE = "TOTAL_TOO_LARGE"
    COMPRESSION_RATIO = "COMPRESSION_RATIO"
    # OPC paket katmanı
    MISSING_CONTENT_TYPES = "MISSING_CONTENT_TYPES"
    MISSING_MAIN_DOCUMENT = "MISSING_MAIN_DOCUMENT"
    MACRO_ENABLED = "MACRO_ENABLED"
    NOT_DOCX = "NOT_DOCX"
    # XML katmanı
    XML_DOCTYPE = "XML_DOCTYPE"
    XML_MALFORMED = "XML_MALFORMED"
    XML_TOO_LARGE = "XML_TOO_LARGE"
    # Parser (A2)
    NOT_WORDML = "NOT_WORDML"
    # Yazıcı (A5) doğrulama kapıları
    WRITE_INVALID_OUTPUT = "WRITE_INVALID_OUTPUT"
    WRITE_TEXT_CHANGED = "WRITE_TEXT_CHANGED"
    WRITE_UNEXPECTED_CHANGE = "WRITE_UNEXPECTED_CHANGE"
    WRITE_STRUCTURE_CHANGED = "WRITE_STRUCTURE_CHANGED"
    WRITE_NOT_RESOLVED = "WRITE_NOT_RESOLVED"
    WRITE_NEW_FINDINGS = "WRITE_NEW_FINDINGS"
    NOTHING_TO_FIX = "NOTHING_TO_FIX"


class SynoraError(Exception):
    """Tüm Synora hatalarının tabanı. Mesaj daima yalnızca hata kodudur."""

    def __init__(self, code: ErrorCode) -> None:
        super().__init__(code.value)
        self.code = code

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.code.value})"


class IngestError(SynoraError):
    """Girdi dosyası güvenlik ya da biçim denetiminden geçemedi (A1)."""


class UnsafeXmlError(IngestError):
    """XML parçası güvensiz ya da bozuk."""


class ParseError(SynoraError):
    """Paket güvenli ama bir Word belgesi olarak yorumlanamıyor (A2)."""
