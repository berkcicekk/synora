"""A5 — Yazıcı çekirdeği: XML düzenleme yardımcıları, izlenen değişiklik, paketleme, doğrulama.

Değişmez kural: tez metni değişmez. Her çıktı beş kapıdan geçmeden kullanıcıya verilmez:

1. content_fingerprint girdiyle aynı.
2. Çıktı A1 (güvenli giriş) ve A2'den (parser) yeniden geçiyor.
3. Yeniden denetim: beklenen bulgular kayboldu, yeni bulgu eklenmedi.
4. Dokunulmayan part'lar bayt bayt aynı.
5. Yapısal sayım: biçim kapları (pPr/rPr/sectPr) dışındaki öğe sayıları beklendiği gibi.
"""

from __future__ import annotations

import copy
import io
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from lxml import etree

from synora.errors import ErrorCode, SynoraError
from synora.fingerprint import content_fingerprint
from synora.ingest import DocxPackage, open_docx
from synora.ooxml import W_NS, w
from synora.package import story_parts
from synora.parse import parse_package

AUTHOR = "Synora"

# OOXML şeması çocuk sırasını zorunlu kılar; Word sırası bozuk belgeyi "bozuk" sayar.
PPR_ORDER = [w(t) for t in (
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
    "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
    "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
    "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc",
    "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle",
    "rPr", "sectPr", "pPrChange",
)]
RPR_ORDER = [w(t) for t in (
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
    "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden",
    "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr",
    "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout", "specVanish",
    "oMath", "rPrChange",
)]
SECTPR_ORDER = [w(t) for t in (
    "headerReference", "footerReference", "footnotePr", "endnotePr", "type", "pgSz", "pgMar",
    "paperSrc", "pgBorders", "lnNumType", "pgNumType", "cols", "formProt", "vAlign", "noEndnote",
    "titlePg", "textDirection", "bidi", "rtlGutter", "docGrid", "printerSettings", "sectPrChange",
)]
FORMAT_CONTAINERS = frozenset({w("pPr"), w("rPr"), w("sectPr")})


class WriteError(SynoraError):
    """Çıktı doğrulama kapısından geçemedi; dosya üretilmez."""


def wq(name: str) -> str:
    """w: ad alanlı öznitelik adı."""
    return f"{{{W_NS}}}{name}"


def ordered_child(parent: Any, tag: str, order: list[str]) -> Any:
    """`tag` çocuğunu bulur ya da şemadaki doğru konuma ekler."""
    existing = parent.find(tag)
    if existing is not None:
        return existing
    el = parent.makeelement(tag, {})
    rank = order.index(tag) if tag in order else len(order)
    for i, c in enumerate(parent):
        if isinstance(c.tag, str) and c.tag in order and order.index(c.tag) > rank:
            parent.insert(i, el)
            return el
    parent.append(el)
    return el


def remove_child(parent: Any, tag: str) -> None:
    el = parent.find(tag)
    if el is not None:
        parent.remove(el)


def ensure_first_child(parent: Any, tag: str) -> Any:
    el = parent.find(tag)
    if el is None:
        el = parent.makeelement(tag, {})
        parent.insert(0, el)
    return el


@dataclass
class RevisionIds:
    """Belgedeki tüm w:id değerlerinin üstünden başlayan, benzersiz revizyon kimlikleri."""

    next_id: int
    date: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))

    @classmethod
    def for_roots(cls, roots: Iterable[Any]) -> RevisionIds:
        highest = 0
        for root in roots:
            for el in root.iter():
                raw = el.get(wq("id")) if isinstance(el.tag, str) else None
                if raw is not None and raw.lstrip("-").isdigit():
                    highest = max(highest, int(raw))
        return cls(highest + 1)

    def take(self) -> str:
        value = self.next_id
        self.next_id += 1
        return str(value)


def normalize_order(parent: Any, order: list[str]) -> None:
    """Bilinen çocukları şema sırasına dizer (kararlı); bilinmeyenler sona kalır.
    Yalnızca sıra değişir, içerik değişmez."""
    rank = {tag: i for i, tag in enumerate(order)}
    children = list(parent)
    keyed = sorted(
        enumerate(children),
        key=lambda ic: (rank.get(ic[1].tag, len(order)) if isinstance(ic[1].tag, str)
                        else len(order), ic[0]),
    )
    if [c for _, c in keyed] != children:
        for c in children:
            parent.remove(c)
        for _, c in keyed:
            parent.append(c)


def tracked_edit(
    container: Any,
    change_tag: str,
    inner_tag: str,
    excluded: frozenset[str],
    ids: RevisionIds,
    edit: Callable[[Any], None],
    order: list[str] | None = None,
) -> bool:
    """`container` (pPr/rPr/sectPr) üzerinde `edit`'i izlenen biçim değişikliği olarak uygular.

    Eski hâl `<w:xxxChange><w:xxx>…eski…</w:xxx></w:xxxChange>` olarak saklanır; Word bunu
    "Synora tarafından biçimlendirildi" diye gösterir ve öğrenci kabul/ret edebilir.
    Kapta zaten bir değişiklik kaydı varsa (öğrencinin kendi izlenen değişikliği) dokunulmaz.
    Gerçek bir değişiklik olmadıysa kayıt eklenmez ve False döner.
    """
    if container.find(change_tag) is not None:
        return False
    before = container.makeelement(inner_tag, {})
    for c in container:
        if isinstance(c.tag, str) and c.tag not in excluded:
            before.append(copy.deepcopy(c))
    snapshot = _children_bytes(container, excluded)
    edit(container)
    if _children_bytes(container, excluded) == snapshot:
        return False
    if order is not None:
        normalize_order(container, order)
        normalize_order(before, order)
    change = container.makeelement(change_tag, {wq("id"): ids.take(), wq("author"): AUTHOR,
                                                 wq("date"): ids.date})
    change.append(before)
    container.append(change)
    return True


def _children_bytes(el: Any, excluded: frozenset[str]) -> bytes:
    return b"".join(
        etree.tostring(c) for c in el if isinstance(c.tag, str) and c.tag not in excluded
    )


PPR_CHANGE_EXCLUDED = frozenset({w("rPr"), w("sectPr"), w("pPrChange")})
RPR_CHANGE_EXCLUDED = frozenset({w("rPrChange")})
SECTPR_CHANGE_EXCLUDED = frozenset({w("headerReference"), w("footerReference"),
                                    w("sectPrChange")})


# --- Paketleme ---------------------------------------------------------------------------


def serialize(root: Any) -> bytes:
    data: bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    return data


def repackage(pkg: DocxPackage, replaced: Mapping[str, bytes]) -> bytes:
    """Özgün part sırasını koruyarak yeniden paketler; yeni part'lar sona eklenir."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, blob in pkg.parts.items():
            zf.writestr(zipfile.ZipInfo(name), replaced.get(name, blob),
                        compress_type=zipfile.ZIP_DEFLATED)
        for name, blob in replaced.items():
            if name not in pkg.parts:
                zf.writestr(zipfile.ZipInfo(name), blob, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


# --- Doğrulama kapıları -------------------------------------------------------------------


def structure_counts(pkg: DocxPackage) -> Counter[str]:
    """Hikâye part'larında biçim kapları dışındaki öğelerin sayımı."""
    from synora import xmlsafe

    counts: Counter[str] = Counter()
    for _, part in story_parts(pkg):
        root = xmlsafe.parse(pkg.parts[part])
        stack = [root]
        while stack:
            el = stack.pop()
            for c in el:
                if not isinstance(c.tag, str) or c.tag in FORMAT_CONTAINERS:
                    continue
                counts[c.tag] += 1
                stack.append(c)
    return counts


FindingKey = tuple[str, str | None, int | None]  # rule_id, para_id, section_index


def verify_output(
    original: DocxPackage,
    output: bytes,
    *,
    modified_parts: set[str],
    expected_structure_delta: Counter[str],
    check_findings: Callable[[DocxPackage], set[FindingKey]],
    before_findings: set[FindingKey],
    must_disappear: set[FindingKey],
    allowed_new: set[str],
) -> DocxPackage:
    # Kapı 2: yeniden güvenli giriş + parser
    try:
        out_pkg = open_docx(output)
        parse_package(out_pkg)
    except SynoraError:
        raise WriteError(ErrorCode.WRITE_INVALID_OUTPUT) from None
    # Kapı 1: metin aynı
    if content_fingerprint(out_pkg) != content_fingerprint(original):
        raise WriteError(ErrorCode.WRITE_TEXT_CHANGED)
    # Kapı 4: dokunulmayan part'lar aynı
    for name, blob in original.parts.items():
        if name not in modified_parts and out_pkg.parts.get(name) != blob:
            raise WriteError(ErrorCode.WRITE_UNEXPECTED_CHANGE)
    # Kapı 5: yapı
    expected = structure_counts(original)
    expected.update(expected_structure_delta)
    if +expected != +structure_counts(out_pkg):
        raise WriteError(ErrorCode.WRITE_STRUCTURE_CHANGED)
    # Kapı 3: yeniden denetim
    after = check_findings(out_pkg)
    if after & must_disappear:
        raise WriteError(ErrorCode.WRITE_NOT_RESOLVED)
    new = {k for k in after - before_findings if k[0] not in allowed_new}
    if new:
        raise WriteError(ErrorCode.WRITE_NEW_FINDINGS)
    return out_pkg
