"""Paragraf rolleri — F2 temel sınıflandırıcısı (stil adı + yapı + yerel desenler).

F3'te ParaFeatures tabanlı sınıflandırıcıyla değiştirilecek. Metin yalnızca bu süreç
içinde, yerel desen kontrolü için okunur; hiçbir yere gönderilmez.

Emin olunamayan paragraflar UNKNOWN olur ve denetlenmez: yanlış alarm, kaçırılan
bulgudan daha pahalıdır (öğrencinin araca güvenini kırar).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from synora.model import DocModel, Paragraph, Role, Story

_HEADING_RE = re.compile(r"(?:heading|başlık|baslik)\s*([1-9])")
_TOC_RE = re.compile(r"(?:toc|içindekiler|ıçindekiler|t\.o\.c\.)\s*\d")
_CAPTION_TEXT_RE = re.compile(r"\s*(şekil|resim|grafik|figure|fig\.)\s*\d", re.IGNORECASE)
_TABLE_CAPTION_TEXT_RE = re.compile(r"\s*(tablo|çizelge|table)\s*\d", re.IGNORECASE)

_NAMED: dict[str, Role] = {
    "title": Role.TITLE,
    "konu başlığı": Role.TITLE,
    "quote": Role.BLOCK_QUOTE,
    "intense quote": Role.BLOCK_QUOTE,
    "alıntı": Role.BLOCK_QUOTE,
    "list paragraph": Role.LIST_ITEM,
    "liste paragraf": Role.LIST_ITEM,
    "bibliography": Role.REFERENCE_ENTRY,
    "kaynakça": Role.REFERENCE_ENTRY,
    "footnote text": Role.FOOTNOTE,
    "dipnot metni": Role.FOOTNOTE,
}
_CAPTION_STYLES = frozenset({"caption", "resim yazısı", "açıklamalı alt yazı"})
_HEADINGS = {1: Role.HEADING_1, 2: Role.HEADING_2, 3: Role.HEADING_3}

SHORT_PARAGRAPH = 120


@dataclass(frozen=True, slots=True)
class RoleDecision:
    role: Role
    confidence: float


def assign_roles(doc: DocModel) -> dict[str, RoleDecision]:
    body = doc.body()
    next_in_table = {
        p.para_id: (i + 1 < len(body) and body[i + 1].in_table) for i, p in enumerate(body)
    }
    return {p.para_id: _classify(p, next_in_table.get(p.para_id, False)) for p in doc.paragraphs}


def _classify(p: Paragraph, followed_by_table: bool) -> RoleDecision:
    if p.story is Story.FOOTNOTE:
        return RoleDecision(Role.FOOTNOTE, 1.0)
    if p.story is Story.ENDNOTE:
        return RoleDecision(Role.ENDNOTE, 1.0)
    if p.story in (Story.HEADER, Story.FOOTER):
        return RoleDecision(Role.HEADER_FOOTER, 1.0)
    if not p.text.strip():
        return RoleDecision(Role.EMPTY, 1.0)
    if p.in_textbox:
        return RoleDecision(Role.TEXTBOX, 1.0)
    if p.in_table:
        return RoleDecision(Role.TABLE_CELL, 1.0)

    name = (p.style_name or "").casefold()
    if "TOC" in p.field_kinds or _TOC_RE.match(name):
        return RoleDecision(Role.TOC_ENTRY, 0.9)
    if m := _HEADING_RE.match(name):
        return RoleDecision(_HEADINGS.get(int(m.group(1)), Role.UNKNOWN), 0.9)
    if p.props.outline_level is not None and p.props.outline_level < 3:
        return RoleDecision(_HEADINGS[p.props.outline_level + 1], 0.8)
    if name in _NAMED:
        return RoleDecision(_NAMED[name], 0.9)
    if name in _CAPTION_STYLES or "SEQ" in p.field_kinds:
        table = _TABLE_CAPTION_TEXT_RE.match(p.text) is not None or followed_by_table
        return RoleDecision(Role.TABLE_CAPTION if table else Role.FIGURE_CAPTION, 0.8)
    if len(p.text) <= SHORT_PARAGRAPH:
        if _TABLE_CAPTION_TEXT_RE.match(p.text):
            return RoleDecision(Role.TABLE_CAPTION, 0.7)
        if _CAPTION_TEXT_RE.match(p.text):
            return RoleDecision(Role.FIGURE_CAPTION, 0.7)
        if p.dominant.bold or p.dominant.all_caps:
            # Normal stilde elle kalınlaştırılmış kısa satır: büyük olasılıkla stilsiz başlık.
            return RoleDecision(Role.UNKNOWN, 0.0)
    if p.numbering is not None and p.numbering.num_format == "bullet":
        return RoleDecision(Role.LIST_ITEM, 0.7)
    return RoleDecision(Role.BODY, 0.6)
