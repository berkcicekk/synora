"""A5 — Yorumlu kopya: her bulgu, belgedeki ilgili paragrafa Word yorumu olarak eklenir.

Belgeye yalnızca yorum işaretleri (commentRangeStart/End + commentReference run'ı) eklenir;
bunlar metin taşımaz, content_fingerprint değişmez. Yorum metinleri Synora'nın Türkçe
mesajlarıdır, tez metni değil. Öğrencinin mevcut yorumları korunur.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from lxml import etree

from synora import xmlsafe
from synora.check import Finding, check
from synora.errors import ErrorCode
from synora.ingest import open_docx
from synora.model import Role, Story
from synora.ooxml import REL_NS, W_NS, rels_part_for, resolve_target, w
from synora.parse import parse_document
from synora.report import ROLE_NAMES, SEVERITY_NAMES, message
from synora.ruleset import Ruleset
from synora.write import AUTHOR, RevisionIds, WriteError, repackage, serialize, verify_output, wq

COMMENTS_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
COMMENTS_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def _comment_lines(findings: list[Finding]) -> list[str]:
    lines = []
    for f in findings:
        role = ROLE_NAMES.get(f.role, "") if f.role else ""
        prefix = f"[{SEVERITY_NAMES[f.severity]}] " + (f"{role}: " if role else "")
        lines.append(prefix + message(f))
    lines.append("Synora otomatik biçim denetimi")
    return lines


def annotate_document(data: bytes, rules: Ruleset) -> bytes:
    pkg = open_docx(data)
    parsed = parse_document(pkg)
    result = check(parsed.doc, rules)
    if not result.findings:
        raise WriteError(ErrorCode.NOTHING_TO_FIX)

    body = [p for p in parsed.doc.paragraphs
            if p.story is Story.BODY and result.roles[p.para_id].role
            not in (Role.EMPTY, Role.TABLE_CELL, Role.TEXTBOX, Role.COVER)]
    first_of_section: dict[int, str] = {}
    for p in body:
        if p.section_index is not None:
            first_of_section.setdefault(p.section_index, p.para_id)
    anchor_default = body[0].para_id if body else None

    by_para: dict[str, list[Finding]] = defaultdict(list)
    for f in result.findings:
        target = f.para_id
        if target is None and f.section_index is not None:
            target = first_of_section.get(f.section_index, anchor_default)
        target = target or anchor_default
        if target is not None:
            by_para[target].append(f)
    if not by_para:
        raise WriteError(ErrorCode.NOTHING_TO_FIX)

    # Yorum part'ı: varsa öğrencinin yorumlarına ekle, yoksa oluştur.
    main = pkg.main_part
    rels_name = rels_part_for(main)
    rels_root = (xmlsafe.parse(pkg.parts[rels_name]) if rels_name in pkg.parts
                 else etree.Element(f"{{{REL_NS}}}Relationships",
                                    nsmap={None: REL_NS}))  # type: ignore[dict-item]
    comments_part = None
    for rel in rels_root.iter(f"{{{REL_NS}}}Relationship"):
        if (rel.get("Type") or "").endswith("/comments") and rel.get("TargetMode") != "External":
            comments_part = resolve_target(main, rel.get("Target") or "")
    replaced: dict[str, bytes] = {}
    if comments_part and comments_part in pkg.parts:
        comments_root = xmlsafe.parse(pkg.parts[comments_part])
    else:
        comments_part = "word/comments.xml"
        if comments_part in pkg.parts:  # ilişkisiz yetim part: dokunma
            raise WriteError(ErrorCode.WRITE_UNEXPECTED_CHANGE)
        comments_root = etree.Element(w("comments"), nsmap={"w": W_NS})
        existing_ids = {r.get("Id") for r in rels_root}
        rid = next(f"rIdSynora{i}" for i in range(1, 1000) if f"rIdSynora{i}" not in existing_ids)
        etree.SubElement(rels_root, f"{{{REL_NS}}}Relationship",
                         Id=rid, Type=COMMENTS_TYPE, Target="comments.xml")
        replaced[rels_name] = serialize(rels_root)
        ct_root = xmlsafe.parse(pkg.parts["[Content_Types].xml"])
        etree.SubElement(ct_root, f"{{{CT_NS}}}Override",
                         PartName="/word/comments.xml", ContentType=COMMENTS_CT)
        replaced["[Content_Types].xml"] = serialize(ct_root)

    ids = RevisionIds.for_roots([*parsed.roots.values(), comments_root])
    para_part = {p.para_id: p.part for p in parsed.doc.paragraphs}
    modified_stories: set[str] = set()
    for pid, findings in by_para.items():
        cid = ids.take()
        comment = etree.SubElement(comments_root, w("comment"))
        comment.set(wq("id"), cid)
        comment.set(wq("author"), AUTHOR)
        comment.set(wq("initials"), "S")
        comment.set(wq("date"), ids.date)
        for line in _comment_lines(findings):
            cp = etree.SubElement(comment, w("p"))
            etree.SubElement(etree.SubElement(cp, w("r")), w("t")).text = line
        _mark_paragraph(parsed.paragraphs[pid].p, cid)
        modified_stories.add(para_part[pid])

    replaced[comments_part] = serialize(comments_root)
    for part in modified_stories:
        replaced[part] = serialize(parsed.roots[part])
    output = repackage(pkg, replaced)

    n = len(by_para)
    before = {(f.rule_id, f.para_id, f.section_index) for f in result.findings}
    verify_output(
        pkg, output,
        modified_parts=set(replaced),
        expected_structure_delta=Counter({w("commentRangeStart"): n, w("commentRangeEnd"): n,
                                          w("commentReference"): n, w("r"): n}),
        check_findings=lambda p: {(f.rule_id, f.para_id, f.section_index)
                                  for f in check(parse_document(p).doc, rules).findings},
        before_findings=before,
        must_disappear=set(),
        allowed_new=set(),
    )
    return output


def _mark_paragraph(p: Any, cid: str) -> None:
    start = p.makeelement(w("commentRangeStart"), {wq("id"): cid})
    ppr = p.find(w("pPr"))
    p.insert(1 if ppr is not None and p.index(ppr) == 0 else 0, start)
    p.append(p.makeelement(w("commentRangeEnd"), {wq("id"): cid}))
    run = p.makeelement(w("r"), {})
    run.append(run.makeelement(w("commentReference"), {wq("id"): cid}))
    p.append(run)
