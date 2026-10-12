"""Biçim okuma ve stil kalıtımı.

Paragraf: docDefaults pPr → paragraf stili zinciri (kökten yaprağa) → doğrudan pPr
Run:      docDefaults rPr → paragraf stili zinciri rPr → karakter stili zinciri → doğrudan rPr
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from synora.model import Alignment, LineRule, LineSpacing, NumberingRef, ParaProps, RunProps
from synora.ooxml import (
    A_NS,
    child,
    measure_twips,
    to_int,
    toggle,
    twips_to_cm,
    twips_to_pt,
    val,
    w,
    wattr,
)

MAX_STYLE_DEPTH = 32

_ALIGN = {
    "left": Alignment.LEFT, "start": Alignment.LEFT,
    "center": Alignment.CENTER,
    "right": Alignment.RIGHT, "end": Alignment.RIGHT,
    "both": Alignment.JUSTIFY, "distribute": Alignment.JUSTIFY,
    "mediumKashida": Alignment.JUSTIFY, "highKashida": Alignment.JUSTIFY,
    "lowKashida": Alignment.JUSTIFY, "thaiDistribute": Alignment.JUSTIFY,
}


@dataclass(frozen=True, slots=True)
class ThemeFonts:
    major: str | None = None
    minor: str | None = None

    @classmethod
    def from_xml(cls, root: Any | None) -> ThemeFonts:
        if root is None:
            return cls()

        def latin(tag: str) -> str | None:
            el = root.find(f".//{{{A_NS}}}{tag}/{{{A_NS}}}latin")
            face = el.get("typeface") if el is not None else None
            return face if isinstance(face, str) and face else None

        return cls(major=latin("majorFont"), minor=latin("minorFont"))

    def resolve(self, theme_ref: str) -> str | None:
        if theme_ref.startswith("major"):
            return self.major
        if theme_ref.startswith("minor"):
            return self.minor
        return None


def read_ppr(ppr: Any | None) -> ParaProps:
    if ppr is None:
        return ParaProps()
    ind = child(ppr, "ind")
    spacing = child(ppr, "spacing")
    num = child(ppr, "numPr")

    first_line: float | None = None
    left = right = None
    if ind is not None:
        left = twips_to_cm(measure_twips(wattr(ind, "left") or wattr(ind, "start")))
        right = twips_to_cm(measure_twips(wattr(ind, "right") or wattr(ind, "end")))
        hanging = measure_twips(wattr(ind, "hanging"))
        first = measure_twips(wattr(ind, "firstLine"))
        if hanging is not None:
            first_line = twips_to_cm(-hanging)
        elif first is not None:
            first_line = twips_to_cm(first)

    before = after = None
    line: LineSpacing | None = None
    if spacing is not None:
        before = twips_to_pt(measure_twips(wattr(spacing, "before")))
        after = twips_to_pt(measure_twips(wattr(spacing, "after")))
        raw_line = measure_twips(wattr(spacing, "line"))
        if raw_line is not None:
            rule = wattr(spacing, "lineRule") or "auto"
            if rule == "exact":
                line = LineSpacing(LineRule.EXACT, round(raw_line / 20, 2))
            elif rule == "atLeast":
                line = LineSpacing(LineRule.AT_LEAST, round(raw_line / 20, 2))
            else:
                line = LineSpacing(LineRule.AUTO, round(raw_line / 240, 3))

    return ParaProps(
        alignment=_ALIGN.get(val(ppr, "jc") or ""),
        indent_left_cm=left,
        indent_right_cm=right,
        first_line_cm=first_line,
        space_before_pt=before,
        space_after_pt=after,
        line_spacing=line,
        keep_next=toggle(ppr, "keepNext"),
        page_break_before=toggle(ppr, "pageBreakBefore"),
        outline_level=to_int(val(ppr, "outlineLvl")),
        num_id=to_int(val(num, "numId")) if num is not None else None,
        num_level=to_int(val(num, "ilvl")) if num is not None else None,
    )


def read_rpr(rpr: Any | None, theme: ThemeFonts) -> RunProps:
    if rpr is None:
        return RunProps()
    font: str | None = None
    fonts = child(rpr, "rFonts")
    if fonts is not None:
        font = wattr(fonts, "ascii") or wattr(fonts, "hAnsi")
        if font is None:
            theme_ref = wattr(fonts, "asciiTheme") or wattr(fonts, "hAnsiTheme")
            font = theme.resolve(theme_ref) if theme_ref else None
    size = to_int(val(rpr, "sz"))
    underline = val(rpr, "u")
    u_el = child(rpr, "u")
    return RunProps(
        font=font,
        size_pt=size / 2 if size is not None and size > 0 else None,
        bold=toggle(rpr, "b"),
        italic=toggle(rpr, "i"),
        underline=None if u_el is None else (underline or "single") != "none",
        all_caps=toggle(rpr, "caps"),
        small_caps=toggle(rpr, "smallCaps"),
        vert_align=val(rpr, "vertAlign"),
    )


@dataclass(frozen=True, slots=True)
class StyleDef:
    style_id: str
    kind: str  # paragraph / character / table / numbering
    name: str | None
    based_on: str | None
    ppr: ParaProps
    rpr: RunProps


class StyleSheet:
    def __init__(self, root: Any | None, theme: ThemeFonts) -> None:
        self.theme = theme
        self.styles: dict[str, StyleDef] = {}
        self.doc_ppr = ParaProps()
        self.doc_rpr = RunProps()
        self.default_paragraph: str | None = None
        self.default_character: str | None = None
        self._para_cache: dict[str, tuple[ParaProps, RunProps]] = {}
        self._char_cache: dict[str, RunProps] = {}
        if root is None:
            return
        defaults = child(root, "docDefaults")
        if defaults is not None:
            self.doc_ppr = read_ppr(child(child(defaults, "pPrDefault"), "pPr"))
            self.doc_rpr = read_rpr(child(child(defaults, "rPrDefault"), "rPr"), theme)
        for el in root.iter(w("style")):
            sid = wattr(el, "styleId")
            if not sid or sid in self.styles:
                continue
            kind = wattr(el, "type") or "paragraph"
            self.styles[sid] = StyleDef(
                style_id=sid,
                kind=kind,
                name=val(el, "name"),
                based_on=val(el, "basedOn"),
                ppr=read_ppr(child(el, "pPr")),
                rpr=read_rpr(child(el, "rPr"), theme),
            )
            if (wattr(el, "default") or "").lower() in ("1", "true", "on"):
                if kind == "paragraph" and self.default_paragraph is None:
                    self.default_paragraph = sid
                elif kind == "character" and self.default_character is None:
                    self.default_character = sid

    def _chain(self, style_id: str | None, kind: str) -> list[StyleDef]:
        """Kökten yaprağa stil zinciri. Döngü ve aşırı derinlik sessizce kesilir."""
        chain: list[StyleDef] = []
        seen: set[str] = set()
        current = style_id
        while current and current not in seen and len(chain) < MAX_STYLE_DEPTH:
            seen.add(current)
            style = self.styles.get(current)
            if style is None or style.kind != kind:
                break
            chain.append(style)
            current = style.based_on
        chain.reverse()
        return chain

    def paragraph_style(self, style_id: str | None) -> tuple[ParaProps, RunProps]:
        key = style_id or ""
        if key not in self._para_cache:
            ppr, rpr = ParaProps(), RunProps()
            for style in self._chain(style_id, "paragraph"):
                ppr, rpr = ppr.merge(style.ppr), rpr.merge(style.rpr)
            self._para_cache[key] = (ppr, rpr)
        return self._para_cache[key]

    def character_style(self, style_id: str | None) -> RunProps:
        key = style_id or ""
        if key not in self._char_cache:
            rpr = RunProps()
            for style in self._chain(style_id, "character"):
                rpr = rpr.merge(style.rpr)
            self._char_cache[key] = rpr
        return self._char_cache[key]

    def name_of(self, style_id: str | None) -> str | None:
        style = self.styles.get(style_id or "")
        return style.name if style else None


class Numbering:
    def __init__(self, root: Any | None) -> None:
        self._levels: dict[str, dict[int, tuple[str | None, str | None]]] = {}
        self._nums: dict[int, str] = {}
        if root is None:
            return
        for abstract in root.iter(w("abstractNum")):
            aid = wattr(abstract, "abstractNumId")
            if aid is None:
                continue
            levels: dict[int, tuple[str | None, str | None]] = {}
            for lvl in abstract.iter(w("lvl")):
                ilvl = to_int(wattr(lvl, "ilvl"))
                if ilvl is not None:
                    levels[ilvl] = (val(lvl, "numFmt"), val(lvl, "lvlText"))
            self._levels[aid] = levels
        for num in root.iter(w("num")):
            nid = to_int(wattr(num, "numId"))
            aid = val(num, "abstractNumId")
            if nid is not None and aid is not None:
                self._nums[nid] = aid

    def lookup(self, num_id: int | None, level: int | None) -> NumberingRef | None:
        if not num_id:  # None ya da 0 (0 = numaralandırmayı kaldır)
            return None
        lvl = level or 0
        fmt, text = self._levels.get(self._nums.get(num_id, ""), {}).get(lvl, (None, None))
        return NumberingRef(num_id=num_id, level=lvl, num_format=fmt, level_text=text)
