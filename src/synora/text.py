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
MAX_INSTRUCTION_CHARS = 256  # alan türü komutun ilk sözcüğüdür; devamı gerekmez
_SURROGATES = range(0xD800, 0xE000)
_REPLACEMENT = "\ufffd"


@dataclass
class _OpenField:
    instruction: str = ""
    kind: str | None = None  # `separate` görülünce dolar: alan artık sonuç evresindedir


@dataclass
class FieldTracker:
    """Karmaşık alan durumu (fldChar begin/separate/end). Paragraflar arası sürer:
    bir içindekiler (TOC) alanı onlarca paragrafa yayılır.

    Her işlem sabit sürelidir: küçük bir dosya on binlerce run ve iç içe alan taşıyabilir."""

    _stack: list[_OpenField] = field(default_factory=list)
    _instructions_open: int = 0

    def begin(self) -> None:
        self._stack.append(_OpenField())
        self._instructions_open += 1

    def instr(self, text: str) -> None:
        if self._stack and self._stack[-1].kind is None:
            top = self._stack[-1]
            top.instruction = (top.instruction + text)[:MAX_INSTRUCTION_CHARS]

    def separate(self) -> None:
        if self._stack and self._stack[-1].kind is None:
            self._stack[-1].kind = field_kind(self._stack[-1].instruction)
            self._instructions_open -= 1

    def end(self) -> None:
        if self._stack and self._stack.pop().kind is None:
            self._instructions_open -= 1

    @property
    def in_instruction(self) -> bool:
        return self._instructions_open > 0

    @property
    def kind(self) -> str | None:
        """En içteki sonuç evresindeki alan. Komut evresi açıkken metin üretilmediği için bu
        özellik fiilen yığının tepesine bakar."""
        for open_field in reversed(self._stack):
            if open_field.kind is not None:
                return open_field.kind
        return None


def sym_char(code: str | None) -> str:
    """w:sym karakteri. Geçersiz kod ve UTF-8'e yazılamayan vekil (surrogate) yerine "\ufffd"."""
    if not code:
        return ""
    try:
        value = int(code, 16)
        return _REPLACEMENT if value in _SURROGATES else chr(value)
    except (ValueError, OverflowError):
        return _REPLACEMENT


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
            emit(sym_char(wattr(c, "char")))
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

