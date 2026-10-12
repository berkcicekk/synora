"""Bulgunun belgedeki yerini öğrencinin bulabileceği biçimde anlatır.

Word paragraf numarası göstermez; bu yüzden "GİRİŞ › 1.1 Amaç · 3. paragraf" gibi bir
başlık yolu üretilir. Rapora yalnızca başlık metinleri (kısaltılmış) girer, gövde metni girmez.
"""

from __future__ import annotations

import re

from synora.classify import RoleDecision
from synora.model import DocModel, Role, Story

_LEVELS = {Role.HEADING_1: 0, Role.HEADING_2: 1, Role.HEADING_3: 2}
_NOT_COUNTED = frozenset({Role.EMPTY, Role.TABLE_CELL, Role.TEXTBOX, Role.COVER})
_STORY_NAMES = {Story.FOOTNOTE: "Dipnotlar", Story.ENDNOTE: "Sonnotlar",
                Story.HEADER: "Üstbilgi", Story.FOOTER: "Altbilgi"}
MAX_TITLE = 48


def _short(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t if len(t) <= MAX_TITLE else t[: MAX_TITLE - 1].rstrip() + "…"


def locations(doc: DocModel, roles: dict[str, RoleDecision]) -> dict[str, str]:
    out: dict[str, str] = {}
    path: list[str | None] = [None, None, None]
    count = 0
    story_counts: dict[Story, int] = {}
    for p in doc.paragraphs:
        role = roles[p.para_id].role
        if p.story is not Story.BODY:
            story_counts[p.story] = story_counts.get(p.story, 0) + 1
            out[p.para_id] = f"{_STORY_NAMES[p.story]} · {story_counts[p.story]}. paragraf"
            continue
        if role is Role.COVER:
            out[p.para_id] = "Kapak sayfası"
            continue
        crumbs_before = " › ".join(x for x in path if x)
        if role in _LEVELS:
            level = _LEVELS[role]
            path[level] = _short(p.text)
            for i in range(level + 1, 3):
                path[i] = None
            count = 0
            out[p.para_id] = " › ".join(x for x in path if x) + " (başlık)"
            continue
        if role not in _NOT_COUNTED:
            count += 1
        where = crumbs_before or "Belgenin başı"
        out[p.para_id] = f"{where} · {count}. paragraf" if count else where
    return out
