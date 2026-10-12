"""Paragraf içindeki run'ları belge sırasıyla yürür; görünen metni ve bağlamı çıkarır.

Hem A2 (parse) hem fingerprint bu tek yürüyücüyü kullanır; böylece "metin nedir"
sorusunun tek bir cevabı olur:

- Görünen metin: w:t, w:tab, w:br, w:cr, w:sym, tire karakterleri; alan sonuçları dahil.
- Hariç: silinmiş metin (w:del, w:moveFrom, w:delText), alan komutları (w:instrText),
  metin kutuları (w:txbxContent; içindeki paragraflar ayrıca yürünür),
  mc:Fallback (aynı içeriğin eski sürüm kopyası).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from synora.ooxml import MC_NS, w, wattr

_MC_CHOICE = f"{{{MC_NS}}}Choice"
_MC_ALT = f"{{{MC_NS}}}AlternateContent"
_CONTAINERS = frozenset(
    w(t) for t in ("hyperlink", "smartTag", "customXml", "sdtContent", "bdo", "dir", "sdt")
)
_DELETED = frozenset({w("del"), w("moveFrom")})
_INSERTED = frozenset({w("ins"), w("moveTo")})
_SKIP_IN_RUN = frozenset({w("rPr"), w("drawing"), w("pict"), w("object"), w("txbxContent")})


@dataclass
class FieldTracker:
    """Karmaşık alan durumu (fldChar begin/separate/end). Paragraflar arası sürer:
    bir içindekiler (TOC) alanı onlarca paragrafa yayılır."""

    _stack: list[list[str]] = field(default_factory=list)  # [komut, evre]

    def begin(self) -> None:
        self._stack.append(["", "instr"])

    def instr(self, text: str) -> None:
        if self._stack and self._stack[-1][1] == "instr":
            self._stack[-1][0] += text

    def separate(self) -> None:
        if self._stack:
            self._stack[-1][1] = "result"

    def end(self) -> None:
        if self._stack:
            self._stack.pop()

    @property
    def in_instruction(self) -> bool:
        return any(phase == "instr" for _, phase in self._stack)

    @property
    def kind(self) -> str | None:
        for instr, phase in reversed(self._stack):
            if phase == "result":
                return field_kind(instr)
        return None


def field_kind(instr: str) -> str:
    words = instr.split()
    return words[0].upper()[:32] if words else "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RunText:
    run: Any  # w:r öğesi
    text: str = field(repr=False)
    deleted: bool
    inserted: bool
    field_kind: str | None
    page_break: bool


def _run_text(r: Any, tracker: FieldTracker) -> tuple[str, str | None, bool]:
    parts: list[str] = []
    kind: str | None = None
    page_break = False

    def emit(s: str) -> None:
        nonlocal kind
        if tracker.in_instruction:
            return
        if not parts:
            kind = tracker.kind
        parts.append(s)

    for c in r:
        tag = c.tag
        if not isinstance(tag, str) or tag in _SKIP_IN_RUN:
            continue
        if tag == w("t"):
            emit(c.text or "")
        elif tag == w("instrText"):
            tracker.instr(c.text or "")
        elif tag == w("fldChar"):
            ftype = wattr(c, "fldCharType")
            if ftype == "begin":
                tracker.begin()
            elif ftype == "separate":
                tracker.separate()
            elif ftype == "end":
                tracker.end()
        elif tag in (w("tab"), w("ptab")):
            emit("\t")
        elif tag in (w("br"), w("cr")):
            if wattr(c, "type") == "page":
                page_break = True
            emit("\n")
        elif tag == w("sym"):
            code = wattr(c, "char")
            try:
                emit(chr(int(code, 16)) if code else "")
            except (ValueError, OverflowError):
                emit("�")
        elif tag == w("noBreakHyphen"):
            emit("‑")
        elif tag == w("softHyphen"):
            emit("­")
        elif tag == _MC_ALT:
            # Run içindeki AlternateContent genelde çizim taşır; metin kutuları ayrıca yürünür.
            continue
    return "".join(parts), kind, page_break


def iter_runs(
    container: Any,
    tracker: FieldTracker,
    *,
    deleted: bool = False,
    inserted: bool = False,
) -> Iterator[RunText]:
    """Bir paragrafın (ya da paragraf içi kabın) run'larını belge sırasıyla verir."""
    for c in container:
        tag = c.tag
        if not isinstance(tag, str):
            continue
        if tag == w("r"):
            text, kind, page_break = _run_text(c, tracker)
            yield RunText(c, text, deleted, inserted, kind, page_break)
        elif tag in _DELETED:
            yield from iter_runs(c, tracker, deleted=True, inserted=inserted)
        elif tag in _INSERTED:
            yield from iter_runs(c, tracker, deleted=deleted, inserted=True)
        elif tag == w("fldSimple"):
            tracker.begin()
            tracker.instr(wattr(c, "instr") or "")
            tracker.separate()
            yield from iter_runs(c, tracker, deleted=deleted, inserted=inserted)
            tracker.end()
        elif tag in _CONTAINERS:
            yield from iter_runs(c, tracker, deleted=deleted, inserted=inserted)
        elif tag == _MC_ALT:
            choice = c.find(_MC_CHOICE)
            if choice is not None:
                yield from iter_runs(choice, tracker, deleted=deleted, inserted=inserted)


def visible_text(p: Any, tracker: FieldTracker) -> str:
    return "".join(rt.text for rt in iter_runs(p, tracker) if not rt.deleted)


TRACKED_CHANGE_TAGS = frozenset(
    {w("ins"), w("del"), w("moveFrom"), w("moveTo"), w("rPrChange"), w("pPrChange"),
     w("sectPrChange"), w("tblPrChange"), w("trPrChange"), w("tcPrChange")}
)

