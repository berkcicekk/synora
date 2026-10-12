"""Synora demo: örnek bir tez üretir, denetler ve gizlilik/güvenlik özelliklerini gösterir.

Çalıştırma:  python -m uv run python scripts/demo.py
Çıktı:       demo/ornek_tez.docx (Word'de açılabilir), demo/rapor.json
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from builders import (  # noqa: E402
    content_types,
    make_docx,
    minimal_parts,
    notes_xml,
    p,
    r,
    zip_parts,
)
from thesis import STYLES, sect  # noqa: E402

from synora.check import check  # noqa: E402
from synora.errors import IngestError  # noqa: E402
from synora.features import extract_features  # noqa: E402
from synora.fingerprint import content_fingerprint  # noqa: E402
from synora.ingest import open_docx  # noqa: E402
from synora.parse import parse_package  # noqa: E402
from synora.report import ingest_message, to_json, to_text  # noqa: E402
from synora.roles import assign_roles  # noqa: E402
from synora.ruleset import load_ruleset  # noqa: E402

CENTER = '<w:jc w:val="center"/><w:ind w:firstLine="0"/>'
LEFT = '<w:jc w:val="left"/><w:ind w:firstLine="0"/>'
H1 = '<w:pStyle w:val="Heading1"/>'
H2 = '<w:pStyle w:val="Heading2"/>'
CAP = '<w:pStyle w:val="Caption"/>'

S1 = ("Bu çalışmada lisansüstü öğrencilerin akademik yazma süreçlerinde karşılaştıkları "
      "biçimsel sorunlar incelenmiştir. Araştırma nitel desende yürütülmüştür.")
S2 = ("Elde edilen bulgular, tez yazım kılavuzlarına uyumun öğrenciler için önemli bir "
      "zaman kaybı kaynağı olduğunu göstermektedir (Demir, 2021).")
S3 = ("Şekil 1.1'de görüldüğü gibi süreç üç aşamadan oluşmaktadır: taslak, biçimlendirme "
      "ve enstitü kontrolü.")
S4 = ("Katılımcıların büyük çoğunluğu biçim hatalarını teslimden hemen önce fark ettiğini "
      "belirtmiştir.")


def build_thesis() -> bytes:
    page_break = p('<w:r><w:br w:type="page"/></w:r>')
    cover = (
        p(r("T.C.", rpr="<w:b/>"), ppr=CENTER)
        + p(r("ZONGULDAK BÜLENT ECEVİT ÜNİVERSİTESİ", rpr="<w:b/>"), ppr=CENTER)
        + p(r("LİSANSÜSTÜ EĞİTİM ENSTİTÜSÜ", rpr="<w:b/>"), ppr=CENTER)
        + p(r("ÖRNEK TEZ ÇALIŞMASI", rpr='<w:b/><w:sz w:val="28"/>'), ppr=CENTER)
        + p("Danışman: Doç. Dr. Örnek DANIŞMAN", ppr=CENTER)
        + p("Zonguldak, 2026", ppr=CENTER)
        + page_break
    )
    front = (
        p("ÖZET", ppr=H1)
        + p(S1)
        + p("İÇİNDEKİLER", ppr=H1)
        + p("GİRİŞ\t1", ppr=LEFT)
        + p("1.1 Araştırmanın Amacı\t2", ppr=LEFT, )
        + p("KAYNAKLAR\t9", ppr=LEFT + sect("lowerRoman"))
    )
    chapter1 = (
        p("1. GİRİŞ", ppr=H1)
        + p(S1)
        # HATA: satır aralığı 1,0 (kılavuz 1,5)
        + p(S2, ppr='<w:spacing w:line="240"/>')
        + p(r(S3), '<w:r><w:footnoteReference w:id="1"/></w:r>')
        + p("Şekil 1.1 Tez yazım süreci", ppr=CAP)
        + p("1.1 Araştırmanın Amacı", ppr=H2)
        # HATA: Calibri 11 punto (kılavuz Times New Roman 12)
        + p(r(S4, rpr='<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/>'))
    )
    # Stilsiz, elle biçimlenmiş bölüm (birçok öğrencinin yaptığı gibi)
    chapter2 = (
        # HATA: yeni sayfada başlamıyor, iki yana yaslı, 12 punto
        p(r("2. YÖNTEM", rpr="<w:b/>"))
        + p(S2)
        + p(r("2.1. Araştırma Deseni", rpr="<w:b/>"), ppr=LEFT)
        # HATA: ilk satır girintisi yok
        + p(S1, ppr='<w:ind w:firstLine="0"/>')
        + p("Tablo 2.1 Katılımcıların dağılımı", ppr=LEFT)
        + "<w:tbl><w:tr><w:tc>" + p("Grup", ppr=LEFT) + "</w:tc><w:tc>"
        + p("Sayı", ppr=LEFT) + "</w:tc></w:tr></w:tbl>"
        + p(r("Araştırmanın sınırlılıkları", rpr="<w:b/>"))  # belirsiz: denetlenmez
        + p(S4)
    )
    refs_ppr = '<w:ind w:left="567" w:hanging="567"/><w:spacing w:line="240"/>'
    back = (
        p(r("KAYNAKLAR", rpr="<w:b/>"), ppr=CENTER + "<w:pageBreakBefore/>")
        + p("Demir, C. (2021). Akademik yazma üzerine bir inceleme. Eğitim ve Bilim, 46(2), "
            "115-134.", ppr=refs_ppr)
        + p("Yılmaz, E. (2019). Tez yazım süreçleri. Ankara: Örnek Yayınevi.", ppr=refs_ppr)
        + sect("decimal")
    )
    notes = notes_xml("footnote", {1: p("Örnek dipnot metni.",
                                         ppr='<w:pStyle w:val="FootnoteText"/>')})
    return make_docx(cover + front + chapter1 + chapter2 + back, styles=STYLES, footnotes=notes)


def banner(title: str) -> None:
    print("\n" + "=" * 72 + f"\n {title}\n" + "=" * 72)


def main() -> None:
    out_dir = ROOT / "demo"
    out_dir.mkdir(exist_ok=True)
    data = build_thesis()
    (out_dir / "ornek_tez.docx").write_bytes(data)
    rules = load_ruleset(ROOT / "rulesets" / "example.yaml")

    pkg = open_docx(data)
    doc = parse_package(pkg)
    result = check(doc, rules)
    (out_dir / "rapor.json").write_text(to_json(result, rules), encoding="utf-8")

    banner("1) DENETİM RAPORU  (demo/ornek_tez.docx)")
    print(to_text(result, rules))

    banner("2) ROLLER: Synora her paragrafı neyin tanıdı?")
    roles = assign_roles(doc)
    for i, para in enumerate(doc.body()):
        if para.in_table:
            continue
        decision = roles[para.para_id]
        preview = para.text.replace("\t", " → ").replace("\n", " ")[:46]
        role, conf = decision.role.value, decision.confidence
        print(f"  ¶{i + 1:>2}  {role:<16} güven {conf:.2f}  {preview}")

    banner("3) GİZLİLİK: yapay zekânın gördüğü veri (metin YOK)")
    target = next(x for x in doc.body() if x.text.startswith("2.1."))
    print(f"  Belgedeki metin   : {target.text!r}")
    feats = extract_features(doc)[target.para_id].model_dump(mode="json")
    shown = {k: feats[k] for k in ("bold", "size_ratio", "alignment", "word_count",
                                     "upper_ratio", "ends_with_sentence_punct",
                                     "number_prefix", "keyword", "starts_page")}
    print(f"  Sınıflandırıcıya giden (özet): {json.dumps(shown, ensure_ascii=False)}")
    print(f"  Toplam {len(feats)} alan; hiçbiri metin değil (yalnızca sayı, enum, evet/hayır).")

    banner("4) METİN KORUMASI: content_fingerprint")
    print(f"  Bu belgenin özeti   : {content_fingerprint(pkg)[:24]}…")
    # .docx sıkıştırılmış bir zip: değişiklik açılmış XML üzerinde yapılıp yeniden paketlenir.
    restyled = _mutate(pkg.parts, "word/styles.xml", 'w:line="360"', 'w:line="480"')
    print(f"  Satır aralığı 1,5→2 : {content_fingerprint(open_docx(restyled))[:24]}…  (aynı)")
    edited = _mutate(pkg.parts, "word/document.xml", "Araştırma nitel", "Araştırma nicel")
    print(f"  'nitel'→'nicel'     : {content_fingerprint(open_docx(edited))[:24]}…  (farklı)")

    banner("5) GÜVENLİK: kötü niyetli dosyalar")
    attacks = {
        "XXE (sunucudaki dosyayı okuma girişimi)": _xxe(),
        "Zip bombası (4 MB → birkaç KB)": _bomb(),
        "Makrolu belge (.docm)": _docm(),
        "Zip olmayan dosya": b"MZ\x90\x00 bu bir exe",
    }
    for name, payload in attacks.items():
        try:
            open_docx(payload)
            print(f"  ✗ {name}: KABUL EDİLDİ")
        except IngestError as exc:
            print(f"  ✓ {name}: reddedildi [{exc.code.value}] — {ingest_message(exc.code)}")


def _mutate(parts: Mapping[str, bytes], name: str, old: str, new: str) -> bytes:
    changed = dict(parts)
    xml = changed[name].decode("utf-8")
    assert old in xml, old
    changed[name] = xml.replace(old, new).encode("utf-8")
    return zip_parts(changed)


def _xxe() -> bytes:
    parts = minimal_parts()
    parts["word/document.xml"] = (b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM '
                                  b'"file:///c:/windows/win.ini">]><d>&x;</d>')
    return zip_parts(parts)


def _bomb() -> bytes:
    parts = minimal_parts()
    parts["word/media/bomb.bin"] = b"\0" * (4 * 1024 * 1024)
    return zip_parts(parts)


def _docm() -> bytes:
    parts = minimal_parts()
    parts["[Content_Types].xml"] = content_types(
        main_type="application/vnd.ms-word.document.macroEnabled.main+xml")
    return zip_parts(parts)


if __name__ == "__main__":
    main()
