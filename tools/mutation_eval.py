"""Bozma (mutasyon) değerlendirmesi: belgenin biçimi tek tek bozulur; Synora bozmayı bulmalı,
düzeltmeli ve metne dokunmamalı.

Her deneme özgün belgenin ayrı bir kopyasında tek bir bozma yapar: o kural için şu an bulgusu
olmayan bir paragrafın ya da bölümün biçimini kılavuz dışına çıkarır (öğrencinin Word'de doğrudan
biçim vermesi gibi; değişiklik izleme yok). Sonra ölçülür:

  yakalandı   aynı paragraf/bölüm için beklenen kuralın bulgusu çıktı
  rol değişti bozma paragrafın rolünü değiştirdi (sınıflandırıcı paragrafın izini kaybetti)
  düzeltildi  fix_document kopya verdi ve bulgu kayboldu
  metin       düzeltilmiş kopyanın content_fingerprint'i özgünle aynı

Bozmalar düzelticiden bağımsız yazılmıştır (aynı kodu paylaşsalar hatalar birbirini gizlerdi).
Belge metni okunmaz ve yazdırılmaz; çıktı yalnızca sayılardır.

Kullanım:
  python -m uv run python tools/mutation_eval.py belge.docx:rulesets/x.yaml [...]
      [--per-type 5] [--seed 0] [--json sonuc.json]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from synora.check import CheckResult, check
from synora.errors import SynoraError
from synora.fingerprint import content_fingerprint
from synora.fix import fix_document
from synora.ingest import open_docx
from synora.model import Paragraph, Role
from synora.ooxml import w
from synora.parse import ParseResult, parse_document, parse_package
from synora.ruleset import RoleRules, Ruleset, load_ruleset
from synora.write import (
    PPR_ORDER,
    RPR_ORDER,
    ensure_first_child,
    ordered_child,
    repackage,
    serialize,
    wq,
)

BAD_FONT = "Comic Sans MS"
SIDES = ("top", "bottom", "left", "right")
PARAGRAPH_PROPS = ("line_spacing", "alignment", "first_line_indent_cm", "space_before_pt",
                   "space_after_pt", "size_pt", "font", "bold")


def _twips(cm: float) -> str:
    return str(round(cm / 2.54 * 1440))


# --- Bozmalar -------------------------------------------------------------------------------
# Her biri (kural, mevcut hedef değer) → canlı XML öğesini bozan işlev. None: uygulanamaz.

Mutator = Callable[[Any], None]


def _ppr(p: Any, tag: str) -> Any:
    return ordered_child(ensure_first_child(p, w("pPr")), w(tag), PPR_ORDER)


def _each_run(runs: list[Any], edit: Callable[[Any], None]) -> None:
    for run in runs:
        edit(ensure_first_child(run, w("rPr")))


def _set_attrs(el: Any, drop: tuple[str, ...] = (), **attrs: str) -> None:
    for name in drop:
        el.attrib.pop(wq(name), None)
    for name, value in attrs.items():
        el.set(wq(name), value)


def paragraph_mutator(prop: str, rr: RoleRules, rules: Ruleset,
                      runs: list[Any]) -> Mutator | None:
    if prop == "line_spacing":
        rule = rr.spacing_rule()
        if rule is None:
            return None
        bad = 1.0 if rule.multiple is not None and rule.multiple >= 1.75 else 2.0
        return lambda p: _set_attrs(_ppr(p, "spacing"), line=str(round(bad * 240)),
                                    lineRule="auto")
    if prop == "alignment":
        if rr.alignment is None:
            return None
        bad_jc = "both" if rr.alignment.value in ("center", "left") else "center"
        if rr.alignment.value == "justify":
            bad_jc = "right"
        return lambda p: _set_attrs(_ppr(p, "jc"), val=bad_jc)
    if prop == "first_line_indent_cm":
        if rr.first_line_indent_cm is None:
            return None
        bad = rr.first_line_indent_cm + 1.0 if rr.first_line_indent_cm >= 0 else 0.5
        return lambda p: _set_attrs(
            _ppr(p, "ind"), drop=("hanging", "firstLineChars", "hangingChars"),
            firstLine=_twips(bad))
    if prop in ("space_before_pt", "space_after_pt"):
        target = getattr(rr, prop)
        if target is None:
            return None
        side = "before" if prop == "space_before_pt" else "after"
        twips = str(round((target + 12) * 20))
        return lambda p: _set_attrs(_ppr(p, "spacing"),
                                    drop=(f"{side}Autospacing", f"{side}Lines"), **{side: twips})
    if not runs:
        return None
    if prop == "size_pt":
        if rr.size_pt is None:
            return None
        half = str(round((rr.size_pt + 2) * 2))

        def size(rpr: Any) -> None:
            _set_attrs(ordered_child(rpr, w("sz"), RPR_ORDER), val=half)
            _set_attrs(ordered_child(rpr, w("szCs"), RPR_ORDER), val=half)
        return lambda _p: _each_run(runs, size)
    if prop == "font":
        if not (rr.font or rules.fonts.allowed):
            return None

        def font(rpr: Any) -> None:
            _set_attrs(ordered_child(rpr, w("rFonts"), RPR_ORDER),
                       drop=("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"),
                       ascii=BAD_FONT, hAnsi=BAD_FONT, eastAsia=BAD_FONT, cs=BAD_FONT)
        return lambda _p: _each_run(runs, font)
    if prop == "bold":
        if rr.bold is not True:
            return None
        return lambda _p: _each_run(
            runs, lambda rpr: _set_attrs(ordered_child(rpr, w("b"), RPR_ORDER), val="0"))
    return None


# --- Deneme ---------------------------------------------------------------------------------


@dataclass
class Target:
    kind: str  # bozma türü, ör. "body.line_spacing" ya da "page.margin.left"
    para_id: str | None = None
    section_index: int | None = None
    role: Role | None = None


@dataclass
class Tally:
    applied: int = 0
    detected: int = 0
    role_changed: int = 0
    fixed: int = 0
    text_changed: int = 0
    refused: Counter[str] = field(default_factory=Counter)


def _matches(result: CheckResult, t: Target) -> bool:
    for f in result.findings:
        if f.rule_id != t.kind:
            continue
        if t.para_id is not None and f.para_id == t.para_id:
            return True
        if t.section_index is not None and f.section_index == t.section_index:
            return True
    return False


def targets(data: bytes, rules: Ruleset, per_type: int, rng: random.Random) -> list[Target]:
    doc = parse_package(open_docx(data))
    result = check(doc, rules)
    present = {(f.rule_id, f.para_id, f.section_index) for f in result.findings}
    by_kind: dict[str, list[Target]] = {}
    for p in doc.paragraphs:
        role = result.roles[p.para_id].role
        rr = rules.roles.get(role)
        if rr is None or not p.text.strip():
            continue
        for prop in PARAGRAPH_PROPS:
            kind = f"{role.value}.{prop}"
            if (kind, p.para_id, None) in present or (kind, p.para_id, p.section_index) in present:
                continue
            if paragraph_mutator(prop, rr, rules, [object()]) is None:
                continue
            by_kind.setdefault(kind, []).append(Target(kind, para_id=p.para_id, role=role))
    margins = rules.page.margins_cm
    if margins is not None:
        for s in doc.sections:
            for side in SIDES:
                kind = f"page.margin.{side}"
                if getattr(margins, side) is None or (kind, None, s.index) in present:
                    continue
                by_kind.setdefault(kind, []).append(Target(kind, section_index=s.index))
    chosen: list[Target] = []
    for kind in sorted(by_kind):
        pool = by_kind[kind]
        chosen.extend(rng.sample(pool, min(per_type, len(pool))))
    return chosen


def _mutate(data: bytes, rules: Ruleset, t: Target) -> bytes | None:
    pkg = open_docx(data)
    parsed: ParseResult = parse_document(pkg)
    if t.para_id is not None:
        elements = parsed.paragraphs[t.para_id]
        para: Paragraph = next(p for p in parsed.doc.paragraphs if p.para_id == t.para_id)
        rr = rules.roles[t.role]  # type: ignore[index]
        prop = t.kind.split(".", 1)[1]
        mutate = paragraph_mutator(prop, rr, rules, [run for run, _ in elements.runs])
        if mutate is None:
            return None
        mutate(elements.p)
        part = para.part
    else:
        sect = parsed.section_elements[t.section_index]  # type: ignore[index]
        margins = rules.page.margins_cm
        if sect is None or margins is None:
            return None
        side = t.kind.rsplit(".", 1)[1]
        pg_mar = sect.find(w("pgMar"))
        if pg_mar is None:
            return None
        pg_mar.set(wq(side), _twips(getattr(margins, side) + 1.5))
        part = pkg.main_part
    return repackage(pkg, {part: serialize(parsed.roots[part])})


def run_trial(data: bytes, rules: Ruleset, t: Target, tally: Tally) -> None:
    mutated = _mutate(data, rules, t)
    if mutated is None:
        return
    original_text = content_fingerprint(open_docx(data))
    if content_fingerprint(open_docx(mutated)) != original_text:
        raise AssertionError(f"bozma metni değiştirdi: {t.kind}")  # aracın kendi hatası
    tally.applied += 1
    result = check(parse_package(open_docx(mutated)), rules)
    if t.para_id is not None and result.roles[t.para_id].role is not t.role:
        tally.role_changed += 1
    if not _matches(result, t):
        return
    tally.detected += 1
    try:
        fixed = fix_document(mutated, rules).docx
    except SynoraError as exc:
        tally.refused[exc.code.value] += 1
        return
    if content_fingerprint(open_docx(fixed)) != original_text:
        tally.text_changed += 1
    if not _matches(check(parse_package(open_docx(fixed)), rules), t):
        tally.fixed += 1


def evaluate(data: bytes, rules: Ruleset, per_type: int = 5, seed: int = 0,
             label: str = "") -> dict[str, Tally]:
    rng = random.Random(f"{seed}:{label}")  # noqa: S311 — örnekleme, kripto değil
    tallies: dict[str, Tally] = {}
    for t in targets(data, rules, per_type, rng):
        run_trial(data, rules, t, tallies.setdefault(t.kind, Tally()))
    return tallies


# --- Rapor ----------------------------------------------------------------------------------


def merge(into: dict[str, Tally], new: dict[str, Tally]) -> None:
    for kind, t in new.items():
        acc = into.setdefault(kind, Tally())
        acc.applied += t.applied
        acc.detected += t.detected
        acc.role_changed += t.role_changed
        acc.fixed += t.fixed
        acc.text_changed += t.text_changed
        acc.refused.update(t.refused)


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:5.1f}%" if whole else "    -"


def render(tallies: dict[str, Tally]) -> str:
    lines = [f"{'bozma':34s} {'uyg.':>5s} {'yakalama':>9s} {'düzeltme':>9s} {'rol değ.':>8s} "
             f"{'metin':>6s}  kapı reddi"]
    total = Tally()
    for kind in sorted(tallies):
        t = tallies[kind]
        merge({"_": total}, {"_": t})
        lines.append(f"{kind:34s} {t.applied:5d} {_pct(t.detected, t.applied):>9s} "
                     f"{_pct(t.fixed, t.detected):>9s} {t.role_changed:8d} "
                     f"{t.text_changed:6d}  {dict(t.refused) or ''}")
    lines.append(f"{'TOPLAM':34s} {total.applied:5d} {_pct(total.detected, total.applied):>9s} "
                 f"{_pct(total.fixed, total.detected):>9s} {total.role_changed:8d} "
                 f"{total.text_changed:6d}  {dict(total.refused) or ''}")
    return "\n".join(lines)


def tally_json(t: Tally) -> dict[str, Any]:
    # asdict, Counter'ı Counter((anahtar, değer) çiftleri) olarak yeniden kurup tuple
    # anahtar üretir; json bunu kabul etmez.
    return {**asdict(t), "refused": dict(t.refused)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pairs", nargs="+", help="belge.docx:kural_seti.yaml")
    ap.add_argument("--per-type", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    overall: dict[str, Tally] = {}
    per_doc: dict[str, dict[str, Any]] = {}
    for pair in args.pairs:
        doc_path, _, ruleset_path = pair.rpartition(":")
        rules = load_ruleset(Path(ruleset_path))
        label = f"{Path(doc_path).parent.name}/{Path(doc_path).name}"
        tallies = evaluate(Path(doc_path).read_bytes(), rules, args.per_type, args.seed, label)
        print(f"\n## {label} ({rules.ruleset})\n{render(tallies)}")
        merge(overall, tallies)
        per_doc[label] = {k: tally_json(v) for k, v in tallies.items()}
    if len(args.pairs) > 1:
        print(f"\n## Hepsi\n{render(overall)}")
    if args.json:
        args.json.write_text(json.dumps(per_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
