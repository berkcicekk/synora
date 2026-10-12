"""Doğrulanmış paket üzerinde ilişki çözümleme ve hikâye (story) part'larının bulunması."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from synora import xmlsafe
from synora.ingest import DocxPackage
from synora.model import Story
from synora.ooxml import (
    REL_ENDNOTES,
    REL_FOOTER,
    REL_FOOTNOTES,
    REL_HEADER,
    REL_NS,
    rels_part_for,
    resolve_target,
)


@dataclass(frozen=True, slots=True)
class Relationship:
    rel_id: str
    rel_type: str
    target_part: str | None  # harici ya da paket dışıysa None


def relationships(pkg: DocxPackage, source_part: str) -> list[Relationship]:
    rels_name = rels_part_for(source_part)
    blob = pkg.parts.get(rels_name)
    if blob is None:
        return []
    out: list[Relationship] = []
    for rel in xmlsafe.parse(blob).iter(f"{{{REL_NS}}}Relationship"):
        rel_id = rel.get("Id") or ""
        rel_type = rel.get("Type") or ""
        target = rel.get("Target") or ""
        part = None
        if rel.get("TargetMode") != "External" and target:
            resolved = resolve_target(source_part, target)
            if resolved is not None and resolved in pkg.parts:
                part = resolved
        out.append(Relationship(rel_id, rel_type, part))
    return out


def related_part(rels: list[Relationship], type_suffix: str) -> str | None:
    for rel in rels:
        if rel.rel_type.endswith(type_suffix) and rel.target_part:
            return rel.target_part
    return None


def story_parts(pkg: DocxPackage) -> list[tuple[Story, str]]:
    """Metin taşıyan part'lar, sabit sırayla: gövde, dipnot, sonnot, üstbilgi, altbilgi."""
    rels = relationships(pkg, pkg.main_part)
    out: list[tuple[Story, str]] = [(Story.BODY, pkg.main_part)]
    for story, suffix in ((Story.FOOTNOTE, REL_FOOTNOTES), (Story.ENDNOTE, REL_ENDNOTES)):
        part = related_part(rels, suffix)
        if part:
            out.append((story, part))
    for story, suffix in ((Story.HEADER, REL_HEADER), (Story.FOOTER, REL_FOOTER)):
        parts = sorted(
            {r.target_part for r in rels if r.rel_type.endswith(suffix) and r.target_part}
        )
        out.extend((story, p) for p in parts)
    return out


def parse_part(pkg: DocxPackage, part: str) -> Any:
    return xmlsafe.parse(pkg.parts[part])
