"""OOXML ad alanları, ilişki tipleri ve saldırgan girdiye dayanıklı değer okuyucular.

Buradaki okuyucular bozuk değerde hata fırlatmaz, None döndürür: belge biçimi
ne kadar tuhaf olursa olsun A2 çökmemeli.
"""

from __future__ import annotations

import posixpath
import re
from typing import Any

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

REL_STYLES = "/styles"
REL_NUMBERING = "/numbering"
REL_THEME = "/theme"
REL_FOOTNOTES = "/footnotes"
REL_ENDNOTES = "/endnotes"
REL_HEADER = "/header"
REL_FOOTER = "/footer"

TWIPS_PER_CM = 1440 / 2.54
TWIPS_PER_PT = 20


def w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def wattr(el: Any, name: str) -> str | None:
    value = el.get(f"{{{W_NS}}}{name}")
    return value if isinstance(value, str) else None


def child(el: Any, tag: str) -> Any | None:
    return el.find(w(tag)) if el is not None else None


def val(el: Any, tag: str) -> str | None:
    """<w:tag w:val="..."/> değeri."""
    c = child(el, tag)
    return wattr(c, "val") if c is not None else None


def toggle(el: Any, tag: str) -> bool | None:
    """Açma/kapama özelliği: <w:b/> → True, <w:b w:val="0"/> → False, yok → None."""
    c = child(el, tag)
    if c is None:
        return None
    v = wattr(c, "val")
    return v is None or v.lower() not in ("0", "false", "off", "none")


def to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


_MEASURE_RE = re.compile(r"(-?\d+(?:\.\d+)?)(mm|cm|in|pt|pc|pi)")
_UNIT_TWIPS = {"mm": TWIPS_PER_CM / 10, "cm": TWIPS_PER_CM, "in": 1440.0, "pt": 20.0,
               "pc": 240.0, "pi": 240.0}


def measure_twips(value: str | None) -> float | None:
    """Twip cinsinden tamsayı ya da (strict OOXML) '2.5cm' gibi evrensel ölçü."""
    if value is None:
        return None
    n = to_int(value)
    if n is not None:
        return float(n)
    m = _MEASURE_RE.fullmatch(value.strip())
    if m is None:
        return None
    return float(m.group(1)) * _UNIT_TWIPS[m.group(2)]


def twips_to_cm(twips: float | None) -> float | None:
    return None if twips is None else round(twips / TWIPS_PER_CM, 3)


def twips_to_pt(twips: float | None) -> float | None:
    return None if twips is None else round(twips / TWIPS_PER_PT, 2)


def resolve_target(source_part: str, target: str) -> str | None:
    """İlişki hedefini paket içi part adına çevirir; paket dışına çıkıyorsa None."""
    if target.startswith("/"):
        joined = target.lstrip("/")
    else:
        joined = posixpath.join(posixpath.dirname(source_part), target)
    normalized = posixpath.normpath(joined)
    if normalized.startswith("..") or normalized.startswith("/") or normalized == ".":
        return None
    return normalized


def rels_part_for(part: str) -> str:
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
