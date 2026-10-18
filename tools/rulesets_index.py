"""rulesets/KAYNAKLAR.md dizinini üretir: her kural setinin üniversitesi, kılavuzu ve resmi kaynağı.

Kullanım: python -m uv run python tools/rulesets_index.py   (dosyayı yeniden yazar)
tests/unit/test_rulesets_index.py dizinin güncel olduğunu denetler.
"""

from __future__ import annotations

import sys
from pathlib import Path

from synora.web.app import discover_rulesets, group_rulesets, order_rulesets

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "rulesets" / "KAYNAKLAR.md"
UNIVERSITIES = ROOT / "tools" / "universiteler.txt"

# Kılavuzu bulunamayan ya da kural seti çıkarılamayan üniversiteler (2026-10-18 taraması).
NOT_FOUND: dict[str, str] = {
    "İhsan Doğramacı Bilkent Üniversitesi": "resmi biçim kuralları bulunamadı",
    "Türk Hava Kurumu Üniversitesi": "bulunamadı",
    "Antalya Belek Üniversitesi": "LEE sitesinde kılavuz yok",
    "Bayburt Üniversitesi": "kılavuz bağlantıları 404 (site taşınmış)",
    "Çankırı Karatekin Üniversitesi": "yalnızca şablon; kurallar metinde yazılı değil",
    "Hakkari Üniversitesi": "kılavuz bağlantıları 404",
    "Iğdır Üniversitesi": "enstitü alan adı çözülmüyor",
    "İstanbul Medeniyet Üniversitesi": "somut değer yok; APA/İSNAD'a yönlendiriyor",
    "İstanbul Üniversitesi": "site JavaScript ile yükleniyor; kılavuza ulaşılamadı",
    "İstanbul Üniversitesi-Cerrahpaşa": "site JavaScript ile yükleniyor; kılavuza ulaşılamadı",
    "Türk-Alman Üniversitesi": "yalnızca şablon (değer yok)",
    "Türk-Japon Bilim ve Teknoloji Üniversitesi": "bulunamadı",
    "Demiroğlu Bilim Üniversitesi": "site açılmıyor",
    "İstanbul Sağlık ve Teknoloji Üniversitesi": "LEE sayfasında kılavuz yok",
    "İstanbul Yeni Yüzyıl Üniversitesi": "bulunamadı",
    "İzmir Demokrasi Üniversitesi": "enstitü alan adları çözülmüyor",
    "Yaşar Üniversitesi": "enstitü sitesi erişimi engelliyor (403)",
    "Kahramanmaraş İstiklal Üniversitesi": "site yalnızca JavaScript ile çalışıyor",
    "Kocaeli Üniversitesi": "site JavaScript ile yükleniyor; kılavuza ulaşılamadı",
    "Kocaeli Sağlık ve Teknoloji Üniversitesi": "LEE sayfasında kılavuz yok",
    "Necmettin Erbakan Üniversitesi": "bağlantılar çalışmıyor; yalnızca şablon",
    "Konya Gıda ve Tarım Üniversitesi": "yalnızca şablon; az değer",
    "Mardin Artuklu Üniversitesi": "sitede yalnızca formlar var",
    "Kapadokya Üniversitesi": "bulunamadı",
    "Sakarya Üniversitesi": "sayfalar dinamik; dosya bağlantısı yok",
    "Sakarya Uygulamalı Bilimler Üniversitesi": "site yalnızca JavaScript ile çalışıyor",
    "Samsun Üniversitesi": "yalnızca şablon; az değer",
}


def render() -> str:
    rulesets = discover_rulesets(ROOT / "rulesets")
    groups = [g for g in group_rulesets(order_rulesets(rulesets, "")) if g.items[0].id != "example"]
    universities = [u.strip() for u in UNIVERSITIES.read_text(encoding="utf-8").splitlines()
                    if u.strip()]
    covered = {g.institution for g in groups}
    missing = [u for u in universities if u not in covered]
    files = sum(len(g.items) for g in groups)
    lines = [
        "# Kural setleri: kaynak dizini",
        "",
        "> Bu dosya `tools/rulesets_index.py` ile üretilir; elle değiştirmeyin.",
        "",
        "Kural setleri üniversitelerin resmi tez yazım kılavuzlarından **otomatik olarak**",
        "çıkarıldı (tarama: 2026-10-18). Her değerin yanında kılavuzdaki madde ya da sayfa",
        "numarası yorum olarak yazılı. **Hiçbiri enstitü tarafından doğrulanmadı**; pilot",
        "kullanımdan önce ilgili enstitüye onaylatılmalı. Kılavuzda belirsiz, aralık olarak",
        "verilmiş ya da kendi içinde çelişen kurallar dosyaya konmadı; `# ÇELİŞKİ:`",
        "yorumlarına bakın.",
        "",
        f"**{len(covered)} üniversite · {files} kural seti** · {len(missing)} üniversite için "
        "kılavuz bulunamadı.",
        "",
        "| Üniversite | Kural seti | Kılavuz |",
        "|---|---|---|",
    ]
    for g in groups:
        for i, r in enumerate(g.items):
            uni = g.institution if i == 0 else ""
            source = r.rules.source or ""
            link = f"[{source}]({r.rules.source_url})" if r.rules.source_url else source
            lines.append(f"| {uni} | `{r.id}` | {link.replace('|', '/')} |")
    lines += ["", "## Kılavuzu bulunamayanlar", "",
              "Arama kotası ve erişim sorunları nedeniyle yeniden denenebilir.", "",
              "| Üniversite | Neden |", "|---|---|"]
    lines += [f"| {u} | {NOT_FOUND.get(u, 'bulunamadı')} |" for u in missing]
    return "\n".join(lines) + "\n"


def main() -> int:
    INDEX.write_text(render(), encoding="utf-8", newline="\n")
    print(f"yazıldı: {INDEX.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
