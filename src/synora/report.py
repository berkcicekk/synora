"""A7 — Rapor: bulguları kullanıcının anlayacağı Türkçe mesajlara ve JSON'a çevirir.

Dil kuralları (marka kiti): yargılamadan tarif et, sayıyla başla, Türkçe ondalık virgülü.
Rapor tez metni içermez.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from typing import Any

from synora import __version__
from synora.check import CheckResult, Finding, Severity
from synora.errors import ErrorCode
from synora.model import Alignment, Role
from synora.ruleset import Ruleset

ROLE_NAMES: dict[Role, str] = {
    Role.TITLE: "Tez başlığı",
    Role.HEADING_1: "1. düzey başlık",
    Role.HEADING_2: "2. düzey başlık",
    Role.HEADING_3: "3. düzey başlık",
    Role.BODY: "Gövde metni",
    Role.BLOCK_QUOTE: "Blok alıntı",
    Role.LIST_ITEM: "Liste maddesi",
    Role.FIGURE_CAPTION: "Şekil başlığı",
    Role.TABLE_CAPTION: "Tablo başlığı",
    Role.REFERENCE_ENTRY: "Kaynakça girdisi",
    Role.TOC_ENTRY: "İçindekiler satırı",
    Role.FOOTNOTE: "Dipnot",
    Role.FRONT_MATTER: "Ön sayfa metni",
    Role.ENDNOTE: "Sonnot",
}
ALIGN_NAMES = {
    Alignment.LEFT.value: "sola yaslı",
    Alignment.CENTER.value: "ortalı",
    Alignment.RIGHT.value: "sağa yaslı",
    Alignment.JUSTIFY.value: "iki yana yaslı",
}
SIDE_NAMES = {"top": "Üst", "bottom": "Alt", "left": "Sol", "right": "Sağ"}
PAGE_NUM_NAMES = {"decimal": "1, 2, 3", "lowerRoman": "i, ii, iii", "upperRoman": "I, II, III"}
POSITION_NAMES = {
    "bottom_left": "sayfanın altında, solda", "bottom_center": "sayfanın altında, ortada",
    "bottom_right": "sayfanın altında, sağda", "top_left": "sayfanın üstünde, solda",
    "top_center": "sayfanın üstünde, ortada", "top_right": "sayfanın üstünde, sağda",
}
SEVERITY_NAMES = {Severity.ERROR: "Hata", Severity.WARNING: "Uyarı", Severity.INFO: "Bilgi"}

INGEST_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.FILE_TOO_LARGE: "Dosya çok büyük. En fazla 50 MB yükleyebilirsiniz.",
    ErrorCode.NOT_A_ZIP: "Bu dosya bir Word belgesi (.docx) değil.",
    ErrorCode.CORRUPT_ZIP: "Dosya bozuk görünüyor. Word'de açıp yeniden kaydedin.",
    ErrorCode.ENCRYPTED: "Dosya parola korumalı. Parolayı kaldırıp yeniden yükleyin.",
    ErrorCode.MACRO_ENABLED: (
        "Makro içeren belgeler (.docm) kabul edilmiyor. .docx olarak kaydedin."
    ),
    ErrorCode.NOT_DOCX: "Bu dosya bir Word belgesi değil.",
    ErrorCode.NOT_WORDML: "Bu dosya bir Word belgesi değil.",
}
DEFAULT_INGEST_MESSAGE = (
    "Dosya güvenlik denetiminden geçemedi. Word'de açıp .docx olarak yeniden kaydedin."
)


def ingest_message(code: ErrorCode) -> str:
    return INGEST_MESSAGES.get(code, DEFAULT_INGEST_MESSAGE)


def _tr_num(value: str) -> str:
    return value.replace(".", ",")


def _length(value: str) -> str:
    """'2.5cm' → '2,5 cm'."""
    if value.endswith("cm"):
        return _tr_num(value[:-2]) + " cm"
    return _tr_num(value)


def _spacing(value: str) -> str:
    if value.startswith("exact:"):
        return "tam " + _tr_num(value.removeprefix("exact:").removesuffix("pt")) + " pt"
    if value.startswith("at_least:"):
        return "en az " + _tr_num(value.removeprefix("at_least:").removesuffix("pt")) + " pt"
    return _tr_num(value)


def message(f: Finding) -> str:
    rid, exp, act = f.rule_id, f.expected, f.actual
    if rid == "document.tracked_changes":
        return ("Belgede değişiklik izleme kayıtları var. Teslimden önce tüm değişiklikleri "
                "kabul edin ya da reddedin.")
    if rid == "page.size":
        return f"Kağıt boyutu {_length(act)}. Kılavuz {exp} istiyor."
    if rid == "page.orientation":
        names = {"portrait": "dikey", "landscape": "yatay"}
        return f"Sayfa yönü {names.get(act, act)}. Kılavuz {names.get(exp, exp)} istiyor."
    if rid.startswith("page.margin."):
        side = SIDE_NAMES.get(rid.rsplit(".", 1)[1], "")
        return f"{side} kenar boşluğu {_length(act)}. Kılavuz {_length(exp)} istiyor."
    if rid == "page_numbering.formats":
        def seq(v: str) -> str:
            return "; sonra ".join(PAGE_NUM_NAMES.get(x, x) for x in v.split(","))
        return f"Sayfa numaralandırma sırası: {seq(act)}. Kılavuz: {seq(exp)}."

    if rid == "page_numbering.position":
        if act == "missing":
            return "Sayfa numarası bulunamadı. Altbilgiye bir sayfa numarası alanı ekleyin."
        return (f"Sayfa numarası {POSITION_NAMES.get(act, act)}. "
                f"Kılavuz {POSITION_NAMES.get(exp, exp)} istiyor.")
    if rid == "page_numbering.decoration":
        return ("Sayfa numarasının yanında parantez ya da tire var. "
                "Kılavuz yalnızca rakam istiyor.")

    prop = rid.split(".", 1)[1] if "." in rid else rid
    if prop == "position":
        thing = "Tablo başlığı tablonun" if rid.startswith("table") else "Şekil yazısı şeklin"
        where = {"above": "üstünde", "below": "altında"}
        return (f"{thing} {where.get(act, act)}. Kılavuz {where.get(exp, exp)} olmasını istiyor. "
                "Word'de başlığı taşıyın.")
    if prop == "case":
        words = act.replace("|", ", ")
        if exp == "title":
            rule = ("her sözcüğün ilk harfi büyük olmalı; “ve”, “veya”, “ile” gibi bağlaçlar "
                    "küçük yazılır")
        else:
            rule = "yalnızca ilk sözcüğün ilk harfi büyük olmalı (özel adlar hariç)"
        return f"Bu başlıkta {rule}. Kontrol edin: {words}."
    if prop == "font":
        return f"Yazı tipi {act.replace('|', ', ')}. Kılavuz {exp.replace('|', ' ya da ')} istiyor."
    if prop == "size_pt":
        return f"Punto {_tr_num(act)}. Kılavuz {_tr_num(exp)} istiyor."
    if prop in ("bold", "italic", "all_caps"):
        label = {"bold": "kalın", "italic": "italik", "all_caps": "büyük harfli"}[prop]
        if exp == "true":
            return f"Metin {label} değil. Kılavuz {label} olmasını istiyor."
        return f"Metin {label}. Kılavuz {label} olmamasını istiyor."
    if prop == "alignment":
        return (f"Hizalama {ALIGN_NAMES.get(act, act)}. "
                f"Kılavuz {ALIGN_NAMES.get(exp, exp)} istiyor.")
    if prop == "line_spacing":
        return f"Satır aralığı {_spacing(act)}. Kılavuz {_spacing(exp)} istiyor."
    if prop == "first_line_indent_cm":
        return f"İlk satır girintisi {_tr_num(act)} cm. Kılavuz {_tr_num(exp)} cm istiyor."
    if prop == "indent_left_cm":
        return f"Sol girinti {_tr_num(act)} cm. Kılavuz {_tr_num(exp)} cm istiyor."
    if prop == "space_before_pt":
        return f"Paragraf öncesi boşluk {_tr_num(act)} pt. Kılavuz {_tr_num(exp)} pt istiyor."
    if prop == "space_after_pt":
        return f"Paragraf sonrası boşluk {_tr_num(act)} pt. Kılavuz {_tr_num(exp)} pt istiyor."
    if prop == "page_break_before":
        return "Yeni sayfada başlamıyor. Kılavuz yeni sayfada başlamasını istiyor."
    return f"{rid}: {act}. Kılavuz {exp} istiyor."


def _group_key(f: Finding) -> tuple[str, str, str, Severity]:
    return (f.rule_id, f.expected, f.actual, f.severity)


def summary(result: CheckResult) -> dict[str, int]:
    errors = sum(f.severity is Severity.ERROR for f in result.findings)
    warnings = sum(f.severity is Severity.WARNING for f in result.findings)
    fixable = sum(f.fixable for f in result.findings)
    return {
        "errors": errors,
        "warnings": warnings,
        "fixable": fixable,
        "checked_paragraphs": result.checked_paragraphs,
        "unknown_paragraphs": result.unknown_paragraphs,
        "cover_paragraphs": result.cover_paragraphs,
    }


def to_json(result: CheckResult, rules: Ruleset) -> str:
    findings: list[dict[str, Any]] = []
    for f in result.findings:
        row = asdict(f)
        row["message"] = message(f)
        findings.append(row)
    doc = {
        "synora_version": __version__,
        "ruleset": {"id": rules.ruleset, "version": rules.version, "name": rules.name},
        "summary": summary(result),
        "findings": findings,
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


def to_text(result: CheckResult, rules: Ruleset, *, max_locations: int = 8) -> str:
    s = summary(result)
    lines = [f"Synora · {rules.name} (kural seti {rules.ruleset} v{rules.version})", ""]
    if not result.findings:
        lines.append("Kılavuza aykırı biçim bulunamadı.")
    else:
        lines.append(
            f"{s['errors']} hata, {s['warnings']} uyarı. "
            f"Otomatik düzeltilebilir: {s['fixable']}."
        )
    if s["cover_paragraphs"]:
        lines.append(
            f"Kapak sayfası ({s['cover_paragraphs']} satır) denetlenmedi; "
            "kapak kuralları bu kural setinde tanımlı değil."
        )
    if s["unknown_paragraphs"]:
        lines.append(
            f"Rolü belirlenemeyen {s['unknown_paragraphs']} paragraf denetlenmedi "
            "(ör. stil kullanılmadan elle biçimlenmiş başlıklar)."
        )

    groups: dict[tuple[str, str, str, Severity], list[Finding]] = defaultdict(list)
    for f in result.findings:
        groups[_group_key(f)].append(f)
    order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    for key in sorted(groups, key=lambda k: (order[k[3]], k[0])):
        items = groups[key]
        first = items[0]
        where = _where(items, max_locations)
        label = ROLE_NAMES.get(first.role, "") if first.role else ""
        prefix = f"[{SEVERITY_NAMES[first.severity]}]"
        head = f"{prefix} {label}: " if label else f"{prefix} "
        lines.append("")
        lines.append(head + message(first))
        if where:
            lines.append(f"    {where}")
    return "\n".join(lines) + "\n"


def _where(items: list[Finding], max_locations: int) -> str:
    paras = [f.para_index for f in items if f.para_index is not None]
    if paras:
        shown = ", ".join(f"¶ {i + 1}" for i in paras[:max_locations])
        extra = len(paras) - max_locations
        more = f" ve {extra} paragraf daha" if extra > 0 else ""
        return f"{len(paras)} paragraf: {shown}{more}"
    sections = sorted({f.section_index for f in items if f.section_index is not None})
    if sections and any(f.para_id is None for f in items):
        return "Bölüm: " + ", ".join(str(i + 1) for i in sections)
    return ""
