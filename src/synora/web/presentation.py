"""Arayüzdeki sayfa çizimi için kural setinden okunan değerler.

Giriş sayfasındaki A4 çizimi süs değil, gerçek kılavuzun özetidir: kenar boşlukları, yazı tipi,
punto, satır aralığı ve girinti doğrudan varsayılan kural setinden gelir.
"""

from __future__ import annotations

from dataclasses import dataclass

from synora.model import Alignment, Role
from synora.ruleset import PAGE_SIZES_CM, Ruleset

ALIGN_TR = {Alignment.CENTER: "ortalı", Alignment.LEFT: "sola yaslı",
            Alignment.RIGHT: "sağa yaslı", Alignment.JUSTIFY: "iki yana yaslı"}


def tr_num(value: float) -> str:
    return f"{round(value, 2):g}".replace(".", ",")


@dataclass(frozen=True)
class PageSpec:
    """SVG koordinatları milimetre cinsindendir (A4 = 210 × 297)."""

    name: str
    width_mm: float
    height_mm: float
    top_mm: float
    bottom_mm: float
    left_mm: float
    right_mm: float
    labels: dict[str, str]  # kenar → "4 cm"
    notes: list[str]  # kenar notları: "Times New Roman · 12 pt"
    indent_mm: float
    line_gap_mm: float  # çizimdeki satır aralığı (gösterim amaçlı ölçekli)

    @property
    def block_width(self) -> float:
        return self.width_mm - self.left_mm - self.right_mm

    @property
    def block_height(self) -> float:
        return self.height_mm - self.top_mm - self.bottom_mm

    @property
    def heading_y(self) -> float:
        return self.top_mm + 8

    def callouts(self) -> list[tuple[str, float, float, float]]:
        """Kenar notları: (metin, hedef x, hedef y, not y). Notlar sayfanın sağında dizilir."""
        lines = self.text_lines()
        if not lines:
            return []
        first = lines[0]
        second_para = next((ln for ln in lines[1:] if ln[0] > self.left_mm + 0.5), first)
        targets = {
            "font": (self.left_mm + self.block_width * 0.45, first[2]),
            "spacing": (self.width_mm - self.right_mm - 8, first[2] + self.line_gap_mm * 2.5),
            "indent": (second_para[0] - self.indent_mm / 2, second_para[2]),
            "heading": (self.width_mm / 2 + 24, self.heading_y),
        }
        keys = []
        for note in self.notes:
            if note.startswith("Satır"):
                keys.append("spacing")
            elif note.startswith("Girinti"):
                keys.append("indent")
            elif note.startswith("Bölüm"):
                keys.append("heading")
            else:
                keys.append("font")
        order = sorted(range(len(self.notes)), key=lambda i: targets[keys[i]][1])
        out: list[tuple[str, float, float, float]] = []
        for slot, i in enumerate(order):
            tx, ty = targets[keys[i]]
            out.append((self.notes[i], round(tx, 1), round(ty, 1), round(40 + slot * 54, 1)))
        return out

    def text_lines(self) -> list[tuple[float, float, float]]:
        """Çizimdeki sahte metin satırları: (x1, x2, y)."""
        lines: list[tuple[float, float, float]] = []
        x0, x1 = self.left_mm, self.width_mm - self.right_mm
        y = self.top_mm + 22  # başlığın altından başla
        paragraph_lengths = [7, 9, 6, 8]
        p = 0
        while y < self.height_mm - self.bottom_mm - 4 and p < 40:
            count = paragraph_lengths[p % len(paragraph_lengths)]
            for i in range(count):
                if y > self.height_mm - self.bottom_mm - 4:
                    break
                start = x0 + (self.indent_mm if i == 0 else 0)
                end = x1 - (self.block_width * 0.35 if i == count - 1 else 0)
                lines.append((round(start, 1), round(end, 1), round(y, 1)))
                y += self.line_gap_mm
            y += self.line_gap_mm * 0.6
            p += 1
        return lines


def page_spec(rules: Ruleset) -> PageSpec:
    width_cm, height_cm = PAGE_SIZES_CM.get(rules.page.size or "A4", (21.0, 29.7))
    m = rules.page.margins_cm
    top = m.top if m and m.top is not None else 2.5
    bottom = m.bottom if m and m.bottom is not None else 2.5
    left = m.left if m and m.left is not None else 2.5
    right = m.right if m and m.right is not None else 2.5

    body = rules.roles.get(Role.BODY)
    heading = rules.roles.get(Role.HEADING_1)
    notes: list[str] = []
    font = (body.font[0] if body and body.font else
            rules.fonts.allowed[0] if rules.fonts.allowed else None)
    if font or (body and body.size_pt):
        size = f" · {tr_num(body.size_pt)} pt" if body and body.size_pt else ""
        notes.append(f"{font or 'Gövde'}{size}")
    spacing = body.spacing_rule() if body else None
    if spacing and spacing.multiple:
        notes.append(f"Satır aralığı {tr_num(spacing.multiple)}")
    if body and body.first_line_indent_cm:
        notes.append(f"Girinti {tr_num(body.first_line_indent_cm)} cm")
    if heading and (heading.size_pt or heading.alignment):
        parts = [f"{tr_num(heading.size_pt)} pt" if heading.size_pt else "",
                 ALIGN_TR.get(heading.alignment, "") if heading.alignment else ""]
        notes.append("Bölüm başlığı " + ", ".join(x for x in parts if x))

    multiple = spacing.multiple if spacing and spacing.multiple else 1.5
    return PageSpec(
        name=rules.name,
        width_mm=width_cm * 10, height_mm=height_cm * 10,
        top_mm=top * 10, bottom_mm=bottom * 10, left_mm=left * 10, right_mm=right * 10,
        labels={"top": f"{tr_num(top)} cm", "bottom": f"{tr_num(bottom)} cm",
                "left": f"{tr_num(left)} cm", "right": f"{tr_num(right)} cm"},
        notes=notes,
        indent_mm=(body.first_line_indent_cm or 0) * 10 if body else 10,
        line_gap_mm=round(4.2 * multiple, 2),
    )


# --- Kılavuz ızgarası (tanıtım sayfası) ------------------------------------------------------


@dataclass(frozen=True)
class RuleTile:
    label: str  # "Sol kenar"
    value: str  # "4 cm"
    tone: str  # cobalt / paper / night / tint
    slot: int  # basamaklı ızgaradaki konum (CSS .slot-N)


def rule_tiles(rules: Ruleset) -> list[RuleTile]:
    """Kılavuzun ölçüleri, basamaklı blok ızgarasında. Değerler kural setinden okunur."""
    spec = page_spec(rules)
    body = rules.roles.get(Role.BODY)
    heading = rules.roles.get(Role.HEADING_1)
    footnote = rules.roles.get(Role.FOOTNOTE)
    items: list[tuple[str, str]] = [("Kağıt", rules.page.size or "A4")]
    items += [("Sol kenar", spec.labels["left"]), ("Üst kenar", spec.labels["top"]),
              ("Sağ kenar", spec.labels["right"]), ("Alt kenar", spec.labels["bottom"])]
    font = rules.fonts.allowed[0] if rules.fonts.allowed else None
    if font:
        items.append(("Yazı tipi", font))
    if body and body.size_pt:
        items.append(("Gövde", f"{tr_num(body.size_pt)} pt"))
    spacing = body.spacing_rule() if body else None
    if spacing and spacing.multiple:
        items.append(("Satır aralığı", tr_num(spacing.multiple)))
    if body and body.first_line_indent_cm:
        items.append(("Girinti", f"{tr_num(body.first_line_indent_cm)} cm"))
    if heading and heading.size_pt:
        items.append(("Bölüm başlığı", f"{tr_num(heading.size_pt)} pt"))
    if footnote and footnote.size_pt:
        items.append(("Dipnot", f"{tr_num(footnote.size_pt)} pt"))
    tones = ["cobalt", "paper", "night", "paper", "cobalt", "tint", "paper", "night", "cobalt",
             "paper", "tint"]
    return [RuleTile(label, value, tones[i % len(tones)], i + 1)
            for i, (label, value) in enumerate(items[:11])]
