"""Synora'da XML'in okunabildiği tek kapı.

Geçerli OOXML parçalarında DOCTYPE bulunmaz. Bu yüzden DOCTYPE içeren her girdi
reddedilir; bu, XXE ve entity genişletme (billion laughs) saldırılarını kökten keser.
Ek savunma olarak parser entity çözmez, ağa çıkmaz, DTD yüklemez.
"""

from __future__ import annotations

from typing import Any

from lxml import etree

from synora.errors import ErrorCode, UnsafeXmlError

DEFAULT_MAX_BYTES = 64 * 1024 * 1024

_DOCTYPE = "<!DOCTYPE"
_DOCTYPE_PATTERNS = (
    _DOCTYPE.encode("ascii"),
    _DOCTYPE.encode("utf-16-le"),
    _DOCTYPE.encode("utf-16-be"),
    _DOCTYPE.encode("utf-32-le"),
    _DOCTYPE.encode("utf-32-be"),
)


def _new_parser() -> etree.XMLParser:
    # Parser nesneleri thread-safe değil; her çağrıda yenisi.
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        collect_ids=False,
    )


def parse(data: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES) -> etree._Element:
    if len(data) > max_bytes:
        raise UnsafeXmlError(ErrorCode.XML_TOO_LARGE)
    if any(p in data for p in _DOCTYPE_PATTERNS):
        raise UnsafeXmlError(ErrorCode.XML_DOCTYPE)
    try:
        root = etree.fromstring(data, parser=_new_parser())
    except (etree.LxmlError, ValueError):
        # lxml mesajları belge parçası içerebilir: zincirleme bilerek kesilir.
        raise UnsafeXmlError(ErrorCode.XML_MALFORMED) from None
    docinfo: Any = root.getroottree().docinfo  # lxml-stubs DocInfo alanlarını eksik tanımlıyor
    if docinfo.doctype or docinfo.internalDTD is not None:
        raise UnsafeXmlError(ErrorCode.XML_DOCTYPE)
    return root
