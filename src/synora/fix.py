"""A5 — Düzeltici: düzeltilebilir bulguları izlenen biçim değişikliği olarak uygular.

Yalnızca biçim kapları (w:pPr, w:rPr, w:sectPr) değişir. Her paragraf/run/bölüm için tek bir
değişiklik kaydı (pPrChange/rPrChange/sectPrChange) oluşur; Word'de "Synora" adıyla görünür.
Çıktı write.verify_output kapılarından geçmezse hiçbir dosya üretilmez.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from synora.check import Finding, check
from synora.errors import ErrorCode
from synora.ingest import DocxPackage, open_docx
from synora.model import RunInfo
from synora.ooxml import TWIPS_PER_CM, w
from synora.parse import ParseResult, parse_document, parse_package
from synora.ruleset import Ruleset
from synora.write import (
    PPR_CHANGE_EXCLUDED,
    PPR_ORDER,
    RPR_CHANGE_EXCLUDED,
    RPR_ORDER,
    SECTPR_CHANGE_EXCLUDED,
    SECTPR_ORDER,
    FindingKey,
    RevisionIds,
    WriteError,
    ensure_first_child,
    ordered_child,
    repackage,
    serialize,
    tracked_edit,
    verify_output,
    wq,
)

PAGE_TWIPS = {"A4": (11906, 16838), "A5": (8391, 11906), "B5": (9979, 14175),
              "Letter": (12240, 15840)}
JC = {"left": "left", "center": "center", "right": "right", "justify": "both"}
DEFAULT_MARGIN_TWIPS = {"top": 1417, "bottom": 1417, "left": 1417, "right": 1417,
                        "header": 708, "footer": 708, "gutter": 0}
ALLOWED_NEW_FINDINGS = {"document.tracked_changes"}

PPrOp = Callable[[Any], None]
RunOp = tuple[Callable[[RunInfo], bool], Callable[[Any], None]]  # (hangi run'lar, düzenleme)


@dataclass(frozen=True)
class FixResult:
    docx: bytes
    fixed: int  # uygulanan bulgu sayısı
    skipped: int  # düzeltilebilir ama uygulanamayan (ör. öğrencinin kendi değişiklik kaydı)


def key(f: Finding) -> FindingKey:
    return (f.rule_id, f.para_id, f.section_index if f.para_id is None else None)


def findings_of(pkg: DocxPackage, rules: Ruleset) -> set[FindingKey]:
    return {key(f) for f in check(parse_package(pkg), rules).findings}


def cm_to_twips(cm: float) -> int:
    return round(cm * TWIPS_PER_CM)


def pt_to_twips(pt: float) -> int:
    return round(pt * 20)


# --- Paragraf düzenlemeleri -----------------------------------------------------------------


def _set(el: Any, **attrs: str | int) -> None:
    for name, value in attrs.items():
        el.set(wq(name), str(value))


def _unset(el: Any, *names: str) -> None:
    for name in names:
        el.attrib.pop(wq(name), None)


def _ppr_op(f: Finding) -> PPrOp | None:
    prop = f.rule_id.split(".", 1)[1]
    exp = f.expected

    if f.rule_id == "page_numbering.position":
        horizontal = exp.split("_")[1]
        return lambda ppr: _set(ordered_child(ppr, w("jc"), PPR_ORDER), val=horizontal)

    if prop == "alignment" and exp in JC:
        return lambda ppr: _set(ordered_child(ppr, w("jc"), PPR_ORDER), val=JC[exp])
    if prop == "line_spacing":
        if exp.startswith("exact:") or exp.startswith("at_least:"):
            rule, amount = exp.split(":")
            twips = pt_to_twips(float(amount.removesuffix("pt")))
            line_rule = "exact" if rule == "exact" else "atLeast"
        else:
            twips, line_rule = round(float(exp) * 240), "auto"
        return lambda ppr: _set(ordered_child(ppr, w("spacing"), PPR_ORDER),
                                line=twips, lineRule=line_rule)
    if prop in ("space_before_pt", "space_after_pt"):
        side = "before" if prop == "space_before_pt" else "after"
        twips = pt_to_twips(float(exp))

        def spacing(ppr: Any) -> None:
            el = ordered_child(ppr, w("spacing"), PPR_ORDER)
            _set(el, **{side: twips})
            _unset(el, f"{side}Autospacing", f"{side}Lines")
        return spacing
    if prop == "first_line_indent_cm":
        value = float(exp)

        def first_line(ppr: Any) -> None:
            el = ordered_child(ppr, w("ind"), PPR_ORDER)
            _unset(el, "firstLine", "hanging", "firstLineChars", "hangingChars")
            if value >= 0:
                _set(el, firstLine=cm_to_twips(value))
            else:
                _set(el, hanging=cm_to_twips(-value))
        return first_line
    if prop == "indent_left_cm":
        twips = cm_to_twips(float(exp))

        def left(ppr: Any) -> None:
            el = ordered_child(ppr, w("ind"), PPR_ORDER)
            _unset(el, "start", "leftChars", "startChars")
            _set(el, left=twips)
        return left
    if prop == "page_break_before":
        def page_break(ppr: Any) -> None:
            el = ordered_child(ppr, w("pageBreakBefore"), PPR_ORDER)
            _unset(el, "val")
        return page_break
    return None


def _run_op(f: Finding) -> RunOp | None:
    prop = f.rule_id.split(".", 1)[1]
    exp = f.expected

    if prop == "font":
        allowed = exp.split("|")
        folded = {a.casefold() for a in allowed}

        def bad_font(info: RunInfo) -> bool:
            return bool(info.props.font) and info.props.font.casefold() not in folded  # type: ignore[union-attr]

        def set_font(rpr: Any) -> None:
            el = ordered_child(rpr, w("rFonts"), RPR_ORDER)
            _unset(el, "asciiTheme", "hAnsiTheme", "cstheme")
            _set(el, ascii=allowed[0], hAnsi=allowed[0], cs=allowed[0])
        return bad_font, set_font
    if prop == "size_pt":
        target = float(exp)
        half_points = round(target * 2)

        def wrong_size(info: RunInfo) -> bool:
            if info.props.vert_align in ("superscript", "subscript"):
                return False
            return info.props.size_pt is None or abs(info.props.size_pt - target) > 0.01

        def set_size(rpr: Any) -> None:
            _set(ordered_child(rpr, w("sz"), RPR_ORDER), val=half_points)
            _set(ordered_child(rpr, w("szCs"), RPR_ORDER), val=half_points)
        return wrong_size, set_size
    if prop in ("bold", "italic", "all_caps") and exp == "true":
        tag = {"bold": "b", "italic": "i", "all_caps": "caps"}[prop]

        def turn_on(rpr: Any) -> None:
            el = ordered_child(rpr, w(tag), RPR_ORDER)
            _unset(el, "val")
        return (lambda info: True), turn_on
    return None


# --- Bölüm düzenlemeleri -----------------------------------------------------------------------


def _pg_mar(sect: Any) -> Any:
    el = ordered_child(sect, w("pgMar"), SECTPR_ORDER)
    for name, default in DEFAULT_MARGIN_TWIPS.items():  # şema tüm öznitelikleri zorunlu tutar
        if el.get(wq(name)) is None:
            el.set(wq(name), str(default))
    return el


def _section_op(f: Finding, rules: Ruleset) -> PPrOp | None:
    rid = f.rule_id
    if rid == "page.size" and rules.page.size:
        short, long_ = PAGE_TWIPS[rules.page.size]

        def size(sect: Any) -> None:
            el = ordered_child(sect, w("pgSz"), SECTPR_ORDER)
            landscape = el.get(wq("orient")) == "landscape"
            _set(el, w=long_ if landscape else short, h=short if landscape else long_)
        return size
    if rid == "page.orientation" and rules.page.orientation:
        landscape = rules.page.orientation == "landscape"

        def orient(sect: Any) -> None:
            el = ordered_child(sect, w("pgSz"), SECTPR_ORDER)
            width, height = int(el.get(wq("w")) or 11906), int(el.get(wq("h")) or 16838)
            short, long_ = sorted((width, height))
            if landscape:
                _set(el, w=long_, h=short, orient="landscape")
            else:
                _set(el, w=short, h=long_)
                _unset(el, "orient")
        return orient
    if rid.startswith("page.margin."):
        side = rid.rsplit(".", 1)[1]
        twips = cm_to_twips(float(f.expected.removesuffix("cm")))
        return lambda sect: _set(_pg_mar(sect), **{side: twips})
    return None


def _page_number_ops(f: Finding, sections: int, current: list[str]) -> dict[int, PPrOp]:
    """Bölüm grupları kılavuzdaki sırayla birebir eşleşiyorsa her bölüme biçim atar."""
    expected = f.expected.split(",")
    groups: list[list[int]] = []
    for i in range(sections):
        if groups and current[groups[-1][0]] == current[i]:
            groups[-1].append(i)
        else:
            groups.append([i])
    if len(groups) != len(expected):
        return {}
    ops: dict[int, PPrOp] = {}
    for fmt, members in zip(expected, groups, strict=True):
        for i in members:
            ops[i] = lambda sect, fmt=fmt: _set(  # type: ignore[misc]
                ordered_child(sect, w("pgNumType"), SECTPR_ORDER), fmt=fmt)
    return ops


# --- Uygulama ------------------------------------------------------------------------------------


def fix_document(data: bytes, rules: Ruleset) -> FixResult:
    pkg = open_docx(data)
    parsed = parse_document(pkg)
    result = check(parsed.doc, rules)
    fixable = [f for f in result.findings if f.fixable]
    if not fixable:
        raise WriteError(ErrorCode.NOTHING_TO_FIX)

    ids = RevisionIds.for_roots(parsed.roots.values())
    para_part = {p.para_id: p.part for p in parsed.doc.paragraphs}
    modified: set[str] = set()
    applied: list[Finding] = []

    by_para: dict[str, list[Finding]] = defaultdict(list)
    by_section: dict[int, list[tuple[Finding, PPrOp]]] = defaultdict(list)
    for f in fixable:
        if f.para_id is not None:
            by_para[f.para_id].append(f)
        elif f.rule_id == "page_numbering.formats":
            current = [s.page_number_format or "decimal" for s in parsed.doc.sections]
            for i, op in _page_number_ops(f, len(parsed.doc.sections), current).items():
                by_section[i].append((f, op))
        elif f.section_index is not None:
            section_op = _section_op(f, rules)
            if section_op is not None:
                by_section[f.section_index].append((f, section_op))

    for pid, findings in by_para.items():
        if _apply_paragraph(parsed, pid, findings, ids):
            applied.extend(findings)
            modified.add(para_part[pid])

    section_done: dict[Finding, bool] = {}
    for index, ops in sorted(by_section.items()):
        ok = _apply_section(parsed, index, [op for _, op in ops], ids)
        for f, _ in ops:
            section_done[f] = section_done.get(f, True) and ok
        if ok:
            modified.add(pkg.main_part)
    applied.extend(f for f, ok in section_done.items() if ok)

    if not applied:
        raise WriteError(ErrorCode.NOTHING_TO_FIX)
    replaced = {part: serialize(parsed.roots[part]) for part in modified}
    output = repackage(pkg, replaced)
    verify_output(
        pkg, output,
        modified_parts=modified,
        expected_structure_delta=Counter(),
        check_findings=lambda p: findings_of(p, rules),
        before_findings={key(f) for f in result.findings},
        must_disappear={key(f) for f in applied},
        allowed_new=ALLOWED_NEW_FINDINGS,
    )
    return FixResult(output, fixed=len(applied), skipped=len(fixable) - len(applied))


def _apply_paragraph(
    parsed: ParseResult, pid: str, findings: list[Finding], ids: RevisionIds
) -> bool:
    elements = parsed.paragraphs[pid]
    ppr_ops = [pop for f in findings if (pop := _ppr_op(f)) is not None]
    run_ops = [rop for f in findings if (rop := _run_op(f)) is not None]
    if len(ppr_ops) + len(run_ops) != len(findings):
        return False  # desteklenmeyen bir bulgu: paragrafa hiç dokunma

    run_plan = [(run, ops) for run, info in elements.runs
                if (ops := [edit for selects, edit in run_ops if selects(info)])]
    # Önce denetle, sonra düzenle: öğrencinin kendi değişiklik kaydı varsa paragrafa hiç dokunma.
    existing_ppr = elements.p.find(w("pPr"))
    if ppr_ops and existing_ppr is not None and existing_ppr.find(w("pPrChange")) is not None:
        return False
    for run, _ in run_plan:
        rpr_el = run.find(w("rPr"))
        if rpr_el is not None and rpr_el.find(w("rPrChange")) is not None:
            return False

    if ppr_ops:
        ppr = ensure_first_child(elements.p, w("pPr"))

        def edit_ppr(container: Any) -> None:
            for op in ppr_ops:
                op(container)
        tracked_edit(ppr, w("pPrChange"), w("pPr"), PPR_CHANGE_EXCLUDED, ids, edit_ppr,
                     PPR_ORDER)

    for run, ops in run_plan:
        rpr = ensure_first_child(run, w("rPr"))

        def edit_rpr(container: Any, ops: list[Callable[[Any], None]] = ops) -> None:
            for op in ops:
                op(container)
        tracked_edit(rpr, w("rPrChange"), w("rPr"), RPR_CHANGE_EXCLUDED, ids, edit_rpr,
                     RPR_ORDER)
    return True


def _apply_section(parsed: ParseResult, index: int, ops: list[PPrOp], ids: RevisionIds) -> bool:
    sect = parsed.section_elements[index] if index < len(parsed.section_elements) else None
    if sect is None:
        if parsed.body is None or index != len(parsed.section_elements) - 1:
            return False
        sect = parsed.body.makeelement(w("sectPr"), {})
        parsed.body.append(sect)  # gövdenin son bölüm ayarları her zaman en sonda
    if sect.find(w("sectPrChange")) is not None:
        return False

    def edit(container: Any) -> None:
        for op in ops:
            op(container)
    tracked_edit(sect, w("sectPrChange"), w("sectPr"), SECTPR_CHANGE_EXCLUDED, ids, edit,
                 SECTPR_ORDER)
    return True
