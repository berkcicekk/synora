"""A6 — Denetim motoru: DocModel + roller + Ruleset → bulgular.

Bulgular metin içermez: yalnızca kural kimliği, konum ve biçim değerleri (expected/actual).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

from synora.features import page_starts
from synora.model import DocModel, LineRule, Paragraph, Role, Section
from synora.roles import RoleDecision, assign_roles
from synora.ruleset import PAGE_SIZES_CM, LineSpacingRule, RoleRules, Ruleset


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    severity: Severity
    expected: str  # makine okunur değer; "1.5", "2.5cm", "Times New Roman"
    actual: str
    fixable: bool
    para_id: str | None = None
    para_index: int | None = None  # gövdedeki sıra (kullanıcıya "¶ 214")
    role: Role | None = None
    section_index: int | None = None
    source: str = "rule"


@dataclass(frozen=True, slots=True)
class CheckResult:
    findings: tuple[Finding, ...]
    roles: dict[str, RoleDecision]
    checked_paragraphs: int
    unknown_paragraphs: int


SKIPPED_ROLES = frozenset(
    {Role.EMPTY, Role.UNKNOWN, Role.TABLE_CELL, Role.TEXTBOX, Role.HEADER_FOOTER, Role.TOC_ENTRY}
)


def check(doc: DocModel, rules: Ruleset) -> CheckResult:
    roles = assign_roles(doc)
    findings: list[Finding] = []
    findings.extend(_document_rules(doc, rules))
    findings.extend(_page_rules(doc.sections, rules))
    findings.extend(_page_numbering(doc.sections, rules))
    checked = unknown = 0
    body = doc.body()
    body_index = {p.para_id: i for i, p in enumerate(body)}
    starts_page = page_starts(body)
    for para in doc.paragraphs:
        decision = roles[para.para_id]
        if decision.role is Role.UNKNOWN:
            unknown += 1
        if decision.role in SKIPPED_ROLES:
            continue
        role_rules = rules.roles.get(decision.role)
        if role_rules is None:
            continue
        checked += 1
        starts = starts_page.get(para.para_id, False)
        for f in _paragraph_rules(para, decision.role, role_rules, rules, starts):
            findings.append(
                _locate(f, para, decision.role, body_index.get(para.para_id))
            )
    return CheckResult(tuple(findings), roles, checked, unknown)


def _locate(f: Finding, para: Paragraph, role: Role, index: int | None) -> Finding:
    return Finding(
        rule_id=f.rule_id, severity=f.severity, expected=f.expected, actual=f.actual,
        fixable=f.fixable, para_id=para.para_id, para_index=index, role=role,
        section_index=para.section_index,
    )


def _num(value: float) -> str:
    return f"{round(value, 2):g}"


def _multiple(value: float) -> str:
    """Satır aralığı katsayısı her zaman ondalıklı: 1 → '1.0'."""
    s = _num(value)
    return s if "." in s else f"{s}.0"


def _missing(value: object) -> str:
    return "tanımsız" if value is None else str(value)


# --- Belge ve sayfa -------------------------------------------------------------------


def _document_rules(doc: DocModel, rules: Ruleset) -> Iterator[Finding]:
    if rules.document.forbid_tracked_changes and doc.has_tracked_changes:
        yield Finding("document.tracked_changes", Severity.WARNING, "false", "true", False)


def _page_rules(sections: tuple[Section, ...], rules: Ruleset) -> Iterator[Finding]:
    page = rules.page
    tol = rules.tolerance.length_cm
    for s in sections:
        def finding(rule_id: str, expected: str, actual: str, s: Section = s) -> Finding:
            return Finding(rule_id, Severity.ERROR, expected, actual, True,
                           section_index=s.index)

        if page.size:
            exp_w, exp_h = PAGE_SIZES_CM[page.size]
            w, h = s.page_width_cm, s.page_height_cm
            if w is None or h is None:
                yield finding("page.size", page.size, "tanımsız")
            else:
                short, long_ = sorted((w, h))
                if abs(short - exp_w) > tol * 2 or abs(long_ - exp_h) > tol * 2:
                    yield finding("page.size", page.size, f"{_num(w)}x{_num(h)}cm")
        if page.orientation:
            actual = "landscape" if s.landscape else "portrait"
            if actual != page.orientation:
                yield finding("page.orientation", page.orientation, actual)
        if page.margins_cm:
            for side in ("top", "bottom", "left", "right"):
                expected = getattr(page.margins_cm, side)
                if expected is None:
                    continue
                actual_cm = getattr(s.margins, f"{side}_cm")
                if actual_cm is None or abs(actual_cm - expected) > tol:
                    shown = "tanımsız" if actual_cm is None else f"{_num(actual_cm)}cm"
                    yield finding(f"page.margin.{side}", f"{_num(expected)}cm", shown)


def _page_numbering(sections: tuple[Section, ...], rules: Ruleset) -> Iterator[Finding]:
    expected = [f.value for f in rules.page_numbering.formats_in_order]
    if not expected:
        return
    actual: list[str] = []
    for s in sections:
        fmt = s.page_number_format or "decimal"
        if not actual or actual[-1] != fmt:
            actual.append(fmt)
    if actual != expected:
        yield Finding("page_numbering.formats", Severity.ERROR, ",".join(expected),
                      ",".join(actual), True)


# --- Paragraf ---------------------------------------------------------------------------


def _paragraph_rules(
    p: Paragraph, role: Role, rr: RoleRules, rules: Ruleset, starts_page: bool
) -> Iterator[Finding]:
    tol = rules.tolerance
    prefix = role.value
    props = p.props

    def err(name: str, expected: str, actual: str) -> Finding:
        return Finding(f"{prefix}.{name}", Severity.ERROR, expected, actual, True)

    allowed = rr.font or rules.fonts.allowed
    if allowed:
        allowed_folded = {f.casefold() for f in allowed}
        bad = sorted({r.props.font for r in p.runs
                      if r.props.font and r.props.font.casefold() not in allowed_folded})
        if bad:
            yield err("font", "|".join(allowed), "|".join(bad))

    d = p.dominant
    if rr.size_pt is not None and (
        d.size_pt is None or abs(d.size_pt - rr.size_pt) > tol.size_pt
    ):
        yield err("size_pt", _num(rr.size_pt), _missing(d.size_pt and _num(d.size_pt)))
    toggles: tuple[tuple[str, bool | None, bool | None], ...] = (
        ("bold", rr.bold, d.bold),
        ("italic", rr.italic, d.italic),
        ("all_caps", rr.all_caps, d.all_caps or _typed_upper(p.text)),
    )
    for name, want, have in toggles:
        if want is not None and bool(have) != want:
            yield err(name, str(want).lower(), str(bool(have)).lower())

    if rr.alignment is not None:
        actual_align = props.alignment.value if props.alignment else "left"
        if actual_align != rr.alignment.value:
            yield err("alignment", rr.alignment.value, actual_align)

    spacing = rr.spacing_rule()
    if spacing is not None:
        f = _line_spacing(spacing, p, tol.line_multiple, tol.spacing_pt)
        if f:
            yield err("line_spacing", *f)

    measures: tuple[tuple[str, float | None, float | None, float], ...] = (
        ("first_line_indent_cm", rr.first_line_indent_cm, props.first_line_cm, tol.length_cm),
        ("indent_left_cm", rr.indent_left_cm, props.indent_left_cm, tol.length_cm),
        ("space_before_pt", rr.space_before_pt, props.space_before_pt, tol.spacing_pt),
        ("space_after_pt", rr.space_after_pt, props.space_after_pt, tol.spacing_pt),
    )
    for name, target, measured, t in measures:
        if target is None:
            continue
        value = measured or 0.0
        if abs(value - target) > t:
            yield err(name, _num(target), _num(value))

    if rr.page_break_before and not starts_page:
        yield err("page_break_before", "true", "false")


def _typed_upper(text: str) -> bool:
    """Metin zaten büyük harfle yazılmışsa (biçim olarak değil) büyük harfli sayılır."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def _line_spacing(
    rule: LineSpacingRule, p: Paragraph, tol_multiple: float, tol_pt: float
) -> tuple[str, str] | None:
    ls = p.props.line_spacing
    actual_rule, actual_value = (ls.rule, ls.value) if ls else (LineRule.AUTO, 1.0)
    if rule.multiple is not None:
        if actual_rule is LineRule.AUTO and abs(actual_value - rule.multiple) <= tol_multiple:
            return None
        return _multiple(rule.multiple), _describe(actual_rule, actual_value)
    want_rule, want = (
        (LineRule.EXACT, rule.exact_pt) if rule.exact_pt is not None
        else (LineRule.AT_LEAST, rule.at_least_pt)
    )
    assert want is not None
    if actual_rule is want_rule and abs(actual_value - want) <= tol_pt:
        return None
    return _describe(want_rule, want), _describe(actual_rule, actual_value)


def _describe(rule: LineRule, value: float) -> str:
    if rule is LineRule.AUTO:
        return _multiple(value)
    return f"{rule.value}:{_num(value)}pt"
