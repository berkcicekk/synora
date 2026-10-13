"""Editör görünümü için belge iskeleti.

Gövde metni rapora GİRMEZ: paragraflar yalnızca rol, satır sayısı tahmini ve hizayla temsil edilir;
yalnızca başlık metinleri (kısaltılmış) tutulur. Bölüm sınırları, tablolar, şekiller ve sayfa
sonları ayrı bloklar olarak yer alır. Her bulgu bir bloğa bağlanır.
"""

from __future__ import annotations

import math
import re
from typing import Any

from synora.check import CheckResult, Finding
from synora.model import Alignment, DocModel, Role, Story

CHARS_PER_LINE = 95
MAX_LINES = 8
MAX_TITLE = 90
_HEADINGS = {Role.HEADING_1: "h1", Role.HEADING_2: "h2", Role.HEADING_3: "h3", Role.TITLE: "h1"}
_PARA_ROLES = {Role.BODY, Role.FRONT_MATTER, Role.REFERENCE_ENTRY, Role.LIST_ITEM,
               Role.BLOCK_QUOTE, Role.UNKNOWN}


def _short(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t if len(t) <= MAX_TITLE else t[: MAX_TITLE - 1].rstrip() + "…"


def _lines(chars: int) -> tuple[int, int]:
    """(satır sayısı, son satır genişliği 1–10)."""
    lines = max(1, min(MAX_LINES, math.ceil(chars / CHARS_PER_LINE)))
    rest = chars % CHARS_PER_LINE if chars < CHARS_PER_LINE * MAX_LINES else CHARS_PER_LINE * 0.6
    last = max(2, min(10, round(10 * (rest or CHARS_PER_LINE) / CHARS_PER_LINE)))
    return lines, last


Blocks = list[dict[str, Any]]


def build_outline(doc: DocModel, result: CheckResult) -> tuple[Blocks, dict[int, int]]:
    """Bloklar ve bulgu sırası → blok sırası eşlemesi."""
    blocks: list[dict[str, Any]] = []
    para_block: dict[str, int] = {}
    section_block: dict[int, int] = {}
    roles = result.roles

    def add(block: dict[str, Any]) -> int:
        last = blocks[-1]["kind"] if blocks else None
        if block["kind"] == "pagebreak" and last in ("pagebreak", "section"):
            return len(blocks) - 1  # art arda sayfa sonu tek gösterilir
        blocks.append(block)
        return len(blocks) - 1

    current_section: int | None = None
    for p in doc.body():
        if p.in_textbox:
            continue
        if p.section_index != current_section:
            current_section = p.section_index
            sec = doc.sections[current_section] if current_section is not None and (
                current_section < len(doc.sections)) else None
            section_block[current_section or 0] = add({
                "kind": "section", "n": (current_section or 0) + 1,
                "numbering": sec.page_number_format if sec else None,
            })
        role = roles[p.para_id].role
        if p.props.page_break_before and blocks:
            add({"kind": "pagebreak"})
        if p.in_table:
            if blocks and blocks[-1]["kind"] == "table":
                para_block[p.para_id] = len(blocks) - 1
            else:
                para_block[p.para_id] = add({"kind": "table"})
            continue
        if role is Role.EMPTY:
            if p.has_drawing:
                para_block[p.para_id] = add({"kind": "figure"})
            if p.has_page_break:
                add({"kind": "pagebreak"})
            continue
        if role in _HEADINGS:
            para_block[p.para_id] = add({"kind": _HEADINGS[role], "text": _short(p.text)})
        elif role is Role.COVER:
            para_block[p.para_id] = add({"kind": "cover", "w": max(3, min(9, len(p.text) // 6))})
        elif role is Role.TOC_ENTRY:
            para_block[p.para_id] = add({"kind": "toc"})
        elif role in (Role.FIGURE_CAPTION, Role.TABLE_CAPTION):
            para_block[p.para_id] = add({"kind": "caption",
                                         "table": role is Role.TABLE_CAPTION})
        else:
            lines, last = _lines(len(p.text.strip()))
            para_block[p.para_id] = add({
                "kind": "para", "lines": lines, "last": last,
                "indent": bool(p.props.first_line_cm and p.props.first_line_cm > 0.2),
                "center": p.props.alignment is Alignment.CENTER,
                "role": role.value if role in _PARA_ROLES else "body",
            })
        if role is Role.UNKNOWN or p.para_id in result.user_roles:
            # Öğrenci bu paragrafın rolünü seçebilir (ya da seçimini değiştirebilir).
            blocks[para_block[p.para_id]]["pid"] = p.para_id
        if p.has_page_break:
            add({"kind": "pagebreak"})

    notes = [p for p in doc.paragraphs if p.story in (Story.FOOTNOTE, Story.ENDNOTE)]
    if notes:
        idx = add({"kind": "notes", "count": len(notes)})
        for p in notes:
            para_block[p.para_id] = idx
    margins = [p for p in doc.paragraphs if p.story in (Story.HEADER, Story.FOOTER)]
    if margins:
        idx = add({"kind": "margins"})
        for p in margins:
            para_block[p.para_id] = idx
    if not blocks:
        add({"kind": "section", "n": 1, "numbering": None})
        section_block[0] = 0

    finding_block: dict[int, int] = {}
    for i, f in enumerate(result.findings):
        finding_block[i] = _block_for(f, para_block, section_block)
    return blocks, finding_block


def _block_for(f: Finding, para_block: dict[str, int], section_block: dict[int, int]) -> int:
    if f.para_id is not None and f.para_id in para_block:
        return para_block[f.para_id]
    if f.section_index is not None and f.section_index in section_block:
        return section_block[f.section_index]
    return min(section_block.values()) if section_block else 0
