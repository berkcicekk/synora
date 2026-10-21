"""A6 — Denetim motoru: DocModel + roller + Ruleset → bulgular.

Bulgular metin içermez: yalnızca kural kimliği, konum ve biçim değerleri (expected/actual).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from synora.features import Keyword, keyword, page_tops
from synora.model import Alignment, DocModel, LineRule, Paragraph, Role, Section, Story
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
    cover_paragraphs: int = 0
    user_roles: dict[str, Role] = field(default_factory=dict)  # uygulanan öğrenci seçimleri


SKIPPED_ROLES = frozenset(
    {Role.EMPTY, Role.UNKNOWN, Role.TEXTBOX, Role.HEADER_FOOTER, Role.TOC_ENTRY, Role.COVER}
)  # table_cell atlanmaz: kural seti table_cell kuralı tanımlıyorsa hücre metni denetlenir


UserRoles = Mapping[str, Role]  # para_id → öğrencinin seçtiği rol

# Öğrencinin "rolü belirsiz" paragraflar için seçebileceği roller.
USER_ROLES = frozenset({
    Role.HEADING_1, Role.HEADING_2, Role.HEADING_3, Role.BODY, Role.BLOCK_QUOTE, Role.LIST_ITEM,
    Role.FIGURE_CAPTION, Role.TABLE_CAPTION, Role.REFERENCE_ENTRY, Role.FRONT_MATTER,
})


def check(
    doc: DocModel, rules: Ruleset, user_roles: UserRoles | None = None,
    *, pin_roles: dict[str, Role] | None = None,
) -> CheckResult:
    """`user_roles`: öğrencinin seçtiği roller. Yalnızca sınıflandırıcının UNKNOWN bıraktığı
    paragraflara ve USER_ROLES içindeki rollere uygulanır; diğerleri sessizce yok sayılır.

    `pin_roles`: yalnızca A5 düzelticinin iç kullanımı. Düzeltme bazı paragrafları yeniden
    sınıflandırabilir; kapı, 'yeni görünen' bulgunun özgün dosyada da var olduğunu kanıtlamak
    için özgünü SON rollerle yeniden denetler. Koşulsuz uygulanır; web'e açılmaz."""
    roles = assign_roles(doc)
    applied: dict[str, Role] = {}
    for pid, role in (user_roles or {}).items():
        current = roles.get(pid)
        if current is not None and current.role is Role.UNKNOWN and role in USER_ROLES:
            roles[pid] = RoleDecision(role=role, confidence=1.0)
            applied[pid] = role
    for pid, role in (pin_roles or {}).items():
        if pid in roles:
            roles[pid] = RoleDecision(role=role, confidence=1.0)
    findings: list[Finding] = []
    findings.extend(_document_rules(doc, rules))
    findings.extend(_required_sections(doc, rules))
    findings.extend(_toc_freshness(doc, roles))
    findings.extend(_page_rules(doc.sections, rules, _chapter_sections(doc, roles)))
    findings.extend(_page_numbering(doc.sections, rules))
    findings.extend(_page_number_position(doc, rules))
    checked = unknown = cover = 0
    body = doc.body()
    body_index = {p.para_id: i for i, p in enumerate(body)}
    starts_page = page_tops(body)
    caption_places = _caption_places(body, roles)
    for para in doc.paragraphs:
        decision = roles[para.para_id]
        if decision.role is Role.UNKNOWN:
            unknown += 1
        elif decision.role is Role.COVER:
            cover += 1
        if decision.role in SKIPPED_ROLES:
            continue
        role_rules = rules.roles.get(decision.role)
        if role_rules is None:
            continue
        checked += 1
        starts = starts_page.get(para.para_id, False)
        place = caption_places.get(para.para_id)
        for f in _paragraph_rules(para, decision.role, role_rules, rules, starts, place):
            findings.append(
                _locate(f, para, decision.role, body_index.get(para.para_id))
            )
    return CheckResult(tuple(findings), roles, checked, unknown, cover, applied)


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
    # Mimari §8: altChunk / gömülü OLE'ye dokunulmaz, uyarı bulgusu üretilir (Ö4).
    if doc.alt_chunks:
        yield Finding("document.alt_chunk", Severity.WARNING, "0", str(doc.alt_chunks), False)
    if doc.embedded_objects:
        yield Finding("document.embedded_object", Severity.WARNING, "0",
                      str(doc.embedded_objects), False)


_TOC_TAIL_RE = re.compile(r"(?:(?:\s*[.·…]){2,}|\t)\s*\d+\s*$|\s+\d+\s*$")


def _toc_freshness(doc: DocModel, roles: dict[str, RoleDecision]) -> Iterator[Finding]:
    """İçindekiler alan sonucu (önbellek) gerçek başlıklarla örtüşüyor mu?

    Öğrenci başlığı değiştirip Word'de dizini güncellemezse (F9) dizin eski kalır.
    Yalnızca ana bölüm başlıkları aranır (ön sayfaların dizinde yer alıp almayacağı
    kılavuzdan kılavuza değişir); rapora başlık metni değil yalnızca sayı çıkar.
    """
    def norm(text: str) -> str:
        text = _TOC_TAIL_RE.sub("", text.strip())
        return " ".join(_tr_lower(_PREFIX_RE.sub("", text)).split())

    toc_entries: list[str] = []
    chapter_heads: list[str] = []
    for p in doc.body():
        if p.in_table or p.in_textbox or not p.text.strip():
            continue
        decision = roles[p.para_id]
        if decision.role is Role.TOC_ENTRY:
            toc_entries.append(norm(p.text))
        elif (decision.role is Role.HEADING_1 and decision.confidence >= 0.9
              and keyword(p.text) is not Keyword.FRONT_TITLE):
            # Yalnızca stil/alan destekli başlıklar: desen tahmini (kapak satırı vb.)
            # dizinde doğal olarak bulunmaz, yanlış alarm olurdu.
            chapter_heads.append(norm(p.text))
    if len(toc_entries) < 2 or not chapter_heads:
        return

    def listed(head: str) -> bool:
        return any(e.startswith(head[:50]) or (len(e) >= 3 and head.startswith(e[:50]))
                   for e in toc_entries)

    # Parantezli ya da çok uzun 'başlıklar' şablon yönergesi kalıbıdır (ör. '(yoksa silinir)').
    candidates = [h for h in chapter_heads if 3 <= len(h) <= 60 and "(" not in h]
    missing = [h for h in candidates if not listed(h)]
    if missing:
        yield Finding("document.toc_stale", Severity.WARNING, "güncel",
                      f"{len(missing)} başlık dizinde yok", False)


def _required_sections(doc: DocModel, rules: Ruleset) -> Iterator[Finding]:
    """Kılavuzun zorunlu saydığı bölümler belgede var mı? Yalnızca bölüm ADLARI (kural
    setinden) raporlanır; tez metni rapora girmez."""
    if not rules.required_sections:
        return
    headings: list[str] = []
    for p in doc.body():
        if p.in_table or p.in_textbox:
            continue
        text = p.text.strip()
        if text and len(text) <= 80:  # bölüm başlığı olabilecek kısa satırlar
            headings.append(_tr_lower(_PREFIX_RE.sub("", text).strip()))
    for name in rules.required_sections:
        # "SONUÇLAR|SONUÇ": kılavuzun kabul ettiği alternatif yazımlar; raporda ilki gösterilir.
        alts = [a.strip() for a in name.split("|") if a.strip()]
        if not any(h.startswith(_tr_lower(a)) for a in alts for h in headings):
            yield Finding("document.missing_section", Severity.ERROR, alts[0],
                          "bulunamadı", False)


def _chapter_sections(doc: DocModel, roles: dict[str, RoleDecision]) -> set[int]:
    """İlk dolu paragrafı birinci düzey başlık olan bölümler (chapter_top kuralı için)."""
    out: set[int] = set()
    seen: set[int] = set()
    for p in doc.body():
        if p.in_table or p.in_textbox or p.section_index is None:
            continue
        if p.section_index in seen or not p.text.strip():
            continue
        seen.add(p.section_index)
        decision = roles.get(p.para_id)
        if decision is not None and decision.role is Role.HEADING_1:
            out.add(p.section_index)
    return out


def _page_rules(sections: tuple[Section, ...], rules: Ruleset,
                chapter_sections: set[int] | None = None) -> Iterator[Finding]:
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
                ok = actual_cm is not None and abs(actual_cm - expected) <= tol
                chapter_top = page.margins_cm.chapter_top
                if (not ok and side == "top" and chapter_top is not None
                        and actual_cm is not None
                        and s.index in (chapter_sections or set())):
                    # Bölüm başlığıyla açılan bölümde üst kenar chapter_top da olabilir
                    # ("bölüm başlığı üst kenardan X cm aşağıda" kuralını bölüm kenarıyla
                    # uygulayan şablonlar; ör. Çankaya, Karabük).
                    ok = abs(actual_cm - chapter_top) <= tol
                gutter = s.margins.gutter_cm or 0
                if not ok and side == "left" and actual_cm is not None and gutter:
                    # Kılavuzların "soldan X cm" kuralı Word'de sol kenar + cilt payı
                    # toplamıyla da sağlanabilir (ör. YTÜ SBE şablonu: 2,5 + 1,5 = 4).
                    ok = abs(actual_cm + gutter - expected) <= tol
                if not ok:
                    shown = "tanımsız" if actual_cm is None else f"{_num(actual_cm)}cm"
                    if actual_cm is not None and side == "left" and gutter:
                        shown += f" (cilt payı {_num(gutter)}cm)"
                    yield finding(f"page.margin.{side}", f"{_num(expected)}cm", shown)


def rule_catalog(rules: Ruleset) -> list[str]:
    """Bu kural setinin denetlediği tüm kural kimlikleri (bulgu çıkmasa da).

    Buradaki adlandırma bu dosyadaki Finding üreticileriyle birebir aynı kalmalı;
    rapor 'denetlendi ve uygun' maddelerini bu listeden çıkarır (Ö2).
    """
    out: list[str] = []
    out.extend("document.missing_section" for _ in rules.required_sections[:1])
    page = rules.page
    if page.size:
        out.append("page.size")
    if page.orientation:
        out.append("page.orientation")
    margins = page.margins_cm
    if margins is not None:
        out.extend(f"page.margin.{side}" for side in ("top", "bottom", "left", "right")
                   if getattr(margins, side) is not None)
    pn = rules.page_numbering
    if pn.formats_in_order:
        out.append("page_numbering.formats")
    if len(pn.formats_in_order) >= 2:
        out.append("page_numbering.restart")
    if pn.position:
        out.append("page_numbering.position")
    if pn.forbid_decoration:
        out.append("page_numbering.decoration")
    simple = ("size_pt", "bold", "italic", "all_caps", "alignment", "first_line_indent_cm",
              "indent_left_cm", "space_before_pt", "space_after_pt", "position", "case")
    for role, rr in rules.roles.items():
        if role in SKIPPED_ROLES:
            continue  # denetlenmeyen rolün kuralı "denetlendi ve uygun" diye iddia edilemez
        prefix = role.value
        if rr.font or rules.fonts.allowed:
            out.append(f"{prefix}.font")
        out.extend(f"{prefix}.{name}" for name in simple if getattr(rr, name) is not None)
        if rr.spacing_rule() is not None:
            out.append(f"{prefix}.line_spacing")
        if rr.page_break_before:
            out.append(f"{prefix}.page_break_before")
    return out


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
        # Hangi bölümün ön bölüm olduğu tahmin edilmez: yalnızca grup sayısı eşleşiyorsa düzeltilir.
        yield Finding("page_numbering.formats", Severity.ERROR, ",".join(expected),
                      ",".join(actual), len(actual) == len(expected))
    if len(expected) >= 2:
        # Ana metne (son biçime, tipik olarak Arap rakamına) geçen bölümde numara 1'den
        # başlamalı ("Giriş'ten itibaren 1, 2, 3…"). Word, start verilmezse saymayı önceki
        # bölümden sürdürür; bu yaygın bir öğrenci hatasıdır. Ön sayfa geçişlerine karışılmaz
        # (kapak sayıldığı için roman numaranın ii/iii'ten sürmesi meşru gelenektir) ve açık
        # bir start değeri bilinçli tercih sayılır.
        body_fmt = expected[-1]
        prev: str | None = None
        for s in sections:
            fmt = s.page_number_format or "decimal"
            if (prev is not None and fmt != prev and fmt == body_fmt
                    and s.page_number_start is None):
                yield Finding("page_numbering.restart", Severity.ERROR, "1",
                              "önceki bölümden devam", False, section_index=s.index)
            prev = fmt


# --- Paragraf ---------------------------------------------------------------------------


def _paragraph_rules(
    p: Paragraph, role: Role, rr: RoleRules, rules: Ruleset, starts_page: bool,
    caption_place: str | None = None,
) -> Iterator[Finding]:
    tol = rules.tolerance
    prefix = role.value
    props = p.props

    def err(name: str, expected: str, actual: str, fixable: bool = True) -> Finding:
        return Finding(f"{prefix}.{name}", Severity.ERROR, expected, actual, fixable)

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
            # Kalın/italik kaldırmak kasıtlı vurguyu (ör. Latince terimler) bozabilir:
            # yalnızca "olmalı" yönündeki bulgular otomatik düzeltilebilir.
            yield err(name, str(want).lower(), str(bool(have)).lower(), fixable=want)

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
            if name == "first_line_indent_cm" and abs(value) <= t and p.text.startswith("	"):
                # Girinti sekmeyle yapılmış: sekme durağının yeri denetlenmez ve ilk satır
                # girintisi eklemek ikinci bir girinti olur; yalnızca uyarı.
                yield Finding(f"{prefix}.{name}", Severity.WARNING, _num(target), "sekme", False)
                continue
            yield err(name, _num(target), _num(value))

    if rr.page_break_before and not starts_page:
        yield err("page_break_before", "true", "false")

    # Yer değiştirmek paragraf sırasını (metni) değiştirir: otomatik düzeltilmez.
    if rr.position and caption_place and caption_place != rr.position:
        yield err("position", rr.position, caption_place, fixable=False)

    if rr.case:
        bad = case_problems(p.text, rr.case)
        if bad:
            yield Finding(f"{prefix}.case", Severity.WARNING, rr.case, "|".join(bad[:5]), False)


# --- Şekil/tablo başlığının yeri ------------------------------------------------------------


def _caption_places(body: tuple[Paragraph, ...], roles: dict[str, RoleDecision]) -> dict[str, str]:
    """Başlığın nesnesine göre yeri: 'above' (nesne sonra gelir) ya da 'below' (önce gelir).
    Aradaki boş paragraflar atlanır; komşu nesne bulunamazsa yer belirsizdir (sözlükte yok)."""
    flow = [p for p in body if not p.in_textbox]
    out: dict[str, str] = {}
    for i, p in enumerate(flow):
        role = roles[p.para_id].role
        if role not in (Role.TABLE_CAPTION, Role.FIGURE_CAPTION) or p.in_table:
            continue

        def is_target(q: Paragraph, table: bool = role is Role.TABLE_CAPTION) -> bool:
            return q.in_table if table else q.has_drawing

        def adjacent(step: int, i: int = i) -> bool:
            j = i + step
            while 0 <= j < len(flow):
                q = flow[j]
                if is_target(q):
                    return True
                if q.text.strip() or q.in_table or q.has_drawing:
                    return False
                j += step
            return False

        after, before = adjacent(+1), adjacent(-1)
        if after and not before:
            out[p.para_id] = "above"
        elif before and not after:
            out[p.para_id] = "below"
    return out


# --- Başlık büyük/küçük harfi -----------------------------------------------------------------

CONJUNCTIONS = frozenset({"ve", "veya", "ile", "ya", "da", "de", "ki", "yahut", "ama", "fakat",
                          "ancak", "hem", "ne", "ise", "ya da", "and", "or", "of", "the", "in"})
_PREFIX_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.)\s*")
# Şekil/tablo başlığı öneki: "Şekil 1.1." / "Tablo 2.3:" — büyük/küçük düzeni başlık
# metnine uygulanır, öneke değil ("Örnek" ilk sözcük sayılır).
_CAPTION_PREFIX_RE = re.compile(
    r"^\s*(?:Şekil|Tablo|Çizelge|Grafik|Resim|Harita|Fotoğraf|Ek)\s+"
    r"(?:\d+(?:\.\d+)*|[A-Z])\.?:?\s*", re.IGNORECASE)
_TR_LOWER = str.maketrans({"I": "ı", "İ": "i"})


def _tr_lower(text: str) -> str:
    return text.translate(_TR_LOWER).lower()


def case_problems(text: str, mode: str) -> list[str]:
    """Kurala uymayan sözcükler. Kısaltmalar (BT, SPSS) ve rakamla başlayanlar atlanır.
    Yalnızca yerel olarak çalışır; metin hiçbir yere gönderilmez."""
    core_text = _CAPTION_PREFIX_RE.sub("", text)
    core_text = _PREFIX_RE.sub("", core_text).strip()
    letters = [c for c in core_text if c.isalpha()]
    if len(letters) > 3 and all(c.isupper() for c in letters):
        return ["TAMAMI BÜYÜK HARF"]
    bad: list[str] = []
    for idx, raw in enumerate(core_text.split()):
        word = raw.strip("“”\"'‘’()[]:;,.!?")
        alpha = [c for c in word if c.isalpha()]
        if not alpha or not word[0].isalpha():
            continue
        if len(alpha) > 1 and all(c.isupper() for c in alpha):
            continue  # kısaltma
        stem = re.split(r"['’]", word)[0]
        is_conj = idx > 0 and _tr_lower(stem) in CONJUNCTIONS
        first_upper = word[0].isupper()
        if mode == "title":
            if (is_conj and first_upper) or (not is_conj and not first_upper):
                bad.append(word)
        elif (idx == 0 and not first_upper) or (idx > 0 and first_upper):
            bad.append(word)
    return bad


# --- Sayfa numarasının yeri -------------------------------------------------------------------

_DECORATION_RE = re.compile(r"[()\[\]\-–—/]")


def _horizontal(p: Paragraph) -> str:
    tabs = len(p.text) - len(p.text.lstrip("\t"))
    if tabs >= 2:
        return "right"
    if tabs == 1:
        return "center"
    return {Alignment.CENTER: "center", Alignment.RIGHT: "right"}.get(
        p.props.alignment or Alignment.LEFT, "left")


def _page_number_position(doc: DocModel, rules: Ruleset) -> Iterator[Finding]:
    pn = rules.page_numbering
    if pn.position is None and not pn.forbid_decoration:
        return
    holders: dict[str, Paragraph] = {}
    for p in doc.paragraphs:
        if p.story in (Story.HEADER, Story.FOOTER) and "PAGE" in p.field_kinds:
            holders.setdefault(p.part, p)
    if not holders:
        yield Finding("page_numbering.position", Severity.ERROR, pn.position or "present",
                      "missing", False)
        return
    seen: set[str] = set()
    header: str | None = None
    footer: str | None = None
    for s in doc.sections:
        # Word'de başvurusu olmayan bölüm, önceki bölümün üst/altbilgisini devralır.
        header = s.headers.get("default", header)
        footer = s.footers.get("default", footer)
        for part, vertical in ((footer, "bottom"), (header, "top")):
            if part is None or part not in holders or part in seen:
                continue
            seen.add(part)
            p = holders[part]
            actual = f"{vertical}_{_horizontal(p)}"
            if pn.position and actual != pn.position:
                # Yalnızca altbilgi/üstbilgi doğruysa ve sekmeyle hizalanmamışsa düzeltilebilir.
                fixable = (vertical == pn.position.split("_")[0]
                           and not p.text.startswith("\t"))
                yield Finding("page_numbering.position", Severity.ERROR, pn.position, actual,
                              fixable, para_id=p.para_id, section_index=s.index)
            if pn.forbid_decoration and _DECORATION_RE.search(p.text):
                yield Finding("page_numbering.decoration", Severity.ERROR, "none", "decorated",
                              False, para_id=p.para_id, section_index=s.index)


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
