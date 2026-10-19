"""Rol doğruluğu: sınıflandırıcı, stil kullanılmamış bir tezde paragraf rollerini ne kadar
doğru buluyor?

Etiket kaynağı ("gümüş" etiket): belgede açıkça Başlık 1–3, resim yazısı (anahtar kelimesiyle),
kaynakça ya da içindekiler stili taşıyan paragrafların stilden gelen rolü. Bu paragrafların
özelliklerinden stil ve anahat düzeyi silinir (stil kullanmayan öğrenci gibi) ve sınıflandırıcıya
yeniden sorulur. Biçim (punto, kalınlık, hizalama…) olduğu gibi kalır.

İnsan etiketi ("altın" etiket) varsa `--labels etiket.json` ile verilir: {"<para_id>": "<rol>"}.
Bu paragraflar stil körleştirmesi olmadan, belgenin olduğu gibi hâliyle değerlendirilir.

Sınırlılık: kapak/ön sayfa bölgesi gibi belge düzeyi özellikler hâlâ stil bilgisinden
yararlanabilir; ölçüm bu yüzden stil kullanmayan gerçek bir tezden biraz iyimserdir.
Belge metni okunmaz ve yazdırılmaz; çıktı yalnızca sayılardır.

Kullanım:
  python -m uv run python tools/role_eval.py belge.docx [belge2.docx ...] [--labels e.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from synora.classify import classify
from synora.features import Keyword, ParaFeatures, StyleKind, extract_features
from synora.ingest import open_docx
from synora.model import Role, Story
from synora.parse import parse_package

_STYLE_LABELS = {
    StyleKind.HEADING_1: Role.HEADING_1,
    StyleKind.HEADING_2: Role.HEADING_2,
    StyleKind.HEADING_3: Role.HEADING_3,
    StyleKind.BIBLIOGRAPHY: Role.REFERENCE_ENTRY,
    StyleKind.TOC: Role.TOC_ENTRY,
}
_HEADINGS = {Role.HEADING_1, Role.HEADING_2, Role.HEADING_3}
_HEADING_STYLES = {StyleKind.HEADING_1, StyleKind.HEADING_2, StyleKind.HEADING_3}
_CAPTION_KEYWORDS = {Keyword.FIGURE_CAPTION: Role.FIGURE_CAPTION,
                     Keyword.TABLE_CAPTION: Role.TABLE_CAPTION}


def silver_label(f: ParaFeatures) -> Role | None:
    """Stilin açıkça söylediği rol; emin olunamayan stil (ör. anahtar kelimesiz resim yazısı,
    tablo içi, metin kutusu) etiketlenmez."""
    if f.story is not Story.BODY or f.in_table or f.in_textbox or f.char_count == 0:
        return None
    if f.style_kind is StyleKind.CAPTION:
        return _CAPTION_KEYWORDS.get(f.keyword)
    return _STYLE_LABELS.get(f.style_kind)


def blind(f: ParaFeatures) -> ParaFeatures:
    return f.model_copy(update={"style_kind": StyleKind.NONE, "outline_level": None,
                                "has_toc_field": False})


@dataclass
class Scores:
    pairs: list[tuple[Role, Role]] = field(default_factory=list)  # (beklenen, bulunan)
    # Başlık stili taşımadığı hâlde başlık sayılan paragraflar: doğruluğu bilinemez, ama yanlış
    # alarmların ana kaynağı bunlardı (kapak satırları, ÖZET sayfası tez adı…). Elle bakılmalı.
    unverified_headings: int = 0

    def add(self, want: Role, got: Role) -> None:
        self.pairs.append((want, got))

    def extend(self, other: Scores) -> None:
        self.pairs.extend(other.pairs)
        self.unverified_headings += other.unverified_headings

    def per_role(self) -> dict[Role, tuple[int, float | None, float, float]]:
        """rol → (destek, kesinlik, duyarlılık, belirsiz oranı). Kesinlik yalnızca bu rolü
        verdiği paragraflar üzerinden; UNKNOWN cevap vermemek sayılır."""
        out: dict[Role, tuple[int, float | None, float, float]] = {}
        for role in sorted({w for w, _ in self.pairs}, key=lambda r: r.value):
            support = sum(w is role for w, _ in self.pairs)
            given = sum(g is role for _, g in self.pairs)
            hit = sum(w is role and g is role for w, g in self.pairs)
            unknown = sum(w is role and g is Role.UNKNOWN for w, g in self.pairs)
            out[role] = (support, hit / given if given else None, hit / support,
                         unknown / support)
        return out

    def overall(self) -> tuple[int, float | None, float]:
        """(etiketli paragraf, kesinlik, kapsam)."""
        decided = [(w, g) for w, g in self.pairs if g is not Role.UNKNOWN]
        precision = sum(w is g for w, g in decided) / len(decided) if decided else None
        coverage = len(decided) / len(self.pairs) if self.pairs else 0.0
        return len(self.pairs), precision, coverage

    def confusion(self, top: int = 8) -> list[tuple[tuple[str, str], int]]:
        wrong = Counter((w.value, g.value) for w, g in self.pairs if w is not g)
        return wrong.most_common(top)


def evaluate(data: bytes, labels: dict[str, Role] | None = None) -> tuple[Scores, Scores]:
    """(stil körleştirilmiş gümüş etiket skoru, insan etiketi skoru)."""
    doc = parse_package(open_docx(data))
    feats = extract_features(doc)
    silver, gold = Scores(), Scores()
    for pid, f in feats.items():
        if labels and pid in labels:
            gold.add(labels[pid], classify(f).role)
            continue
        want = silver_label(f)
        if want is not None:
            silver.add(want, classify(blind(f)).role)
        elif f.story is Story.BODY and f.style_kind not in _HEADING_STYLES and (
                classify(f).role in _HEADINGS):
            silver.unverified_headings += 1
    return silver, gold


def _fmt(x: float | None) -> str:
    return f"{100 * x:5.1f}%" if x is not None else "    -"


def render(scores: Scores, title: str) -> str:
    n, precision, coverage = scores.overall()
    lines = [f"{title}: {n} etiketli paragraf · kesinlik {_fmt(precision)} · "
             f"kapsam {_fmt(coverage)} · başlık stili olmadan başlık sayılan "
             f"{scores.unverified_headings}",
             f"  {'rol':16s} {'destek':>6s} {'kesinlik':>9s} {'duyarlılık':>11s} "
             f"{'belirsiz':>9s}"]
    for role, (support, p, r, u) in scores.per_role().items():
        lines.append(f"  {role.value:16s} {support:6d} {_fmt(p):>9s} {_fmt(r):>11s} {_fmt(u):>9s}")
    if scores.confusion():
        lines.append("  en sık karışanlar: " + ", ".join(
            f"{w}→{g} ×{k}" for (w, g), k in scores.confusion()))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("docs", nargs="+", type=Path)
    ap.add_argument("--labels", type=Path, help='{"<para_id>": "<rol>"} (tek belgeyle)')
    args = ap.parse_args(argv)
    labels = None
    if args.labels:
        raw = json.loads(args.labels.read_text(encoding="utf-8"))
        labels = {pid: Role(v) for pid, v in raw.items()}
    total_silver, total_gold = Scores(), Scores()
    for path in args.docs:
        silver, gold = evaluate(path.read_bytes(), labels)
        print(render(silver, f"\n## {path.parent.name}/{path.name} · stil körleştirilmiş"))
        if gold.pairs:
            print(render(gold, "   insan etiketi"))
        total_silver.extend(silver)
        total_gold.extend(gold)
    if len(args.docs) > 1:
        print(render(total_silver, "\n## Hepsi · stil körleştirilmiş"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
