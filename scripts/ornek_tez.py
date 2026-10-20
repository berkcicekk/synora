"""Web demosundaki örnek tez (zbeu-tip formatında): sentetik, bilinçli hatalı.

Çalıştırma: uv run python scripts/ornek_tez.py  →  src/synora/web/static/ornek-tez.docx
Tüm metin sentetiktir; hatalar /demo sayfasının vitrinidir.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

from synora.ruleset import load_ruleset
from synora.word import (
    OFFICE_REL,
    REL_NS,
    W_NS,
    XML_DECL,
    _sect_pr,
    _styles_xml,
    escape,
)

STATIC = Path(__file__).resolve().parents[1] / "src" / "synora" / "web" / "static"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else STATIC
rules = load_ruleset("rulesets/zbeu-tip.yaml")

GOVDE = ("Bu çalışmada sentetik bir hasta grubunun demografik ve klinik özellikleri, "
         "tamamen uydurma veriler üzerinden incelenmiştir. Bu paragraf yalnızca biçim "
         "denetimini sınamak için üretilmiş örnek bir gövde metnidir ve hiçbir gerçek "
         "çalışmayı ya da kişiyi temsil etmez. Cümleler bilinçli olarak uzun tutulmuştur "
         "ki satır sonu davranışı ve iki yana yaslama gerçekçi biçimde sınansın.")


def p(text: str, style: str | None = None, ppr: str = "", rpr: str = "") -> str:
    style_xml = f'<w:pStyle w:val="{style}"/>' if style else ""
    ppr_el = f"<w:pPr>{style_xml}{ppr}</w:pPr>" if (style_xml or ppr) else ""
    rpr_el = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    run = f'<w:r>{rpr_el}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>' if text else ""
    return f"<w:p>{ppr_el}{run}</w:p>"


manifest: list[dict] = []


def planted(no: int, rule_id: str, nerede: str, fixable: bool) -> None:
    manifest.append({"no": no, "rule_id": rule_id, "nerede": nerede, "fixable": fixable})


# --- Gövde -----------------------------------------------------------------------------------
parts: list[str] = []

# Ön sayfalar (lowerRoman bölümü)
parts.append(p("İÇİNDEKİLER", "Heading1"))
parts.append(p("Bu dizin temsilidir; gerçek tezde alan (TOC) kullanılır.", None))
parts.append(p("ÖNSÖZ", "Heading1"))
parts.append(p("Bu sentetik önsöz, saha testi için üretilmiştir. Katkısı olmayan hiç kimseye "
               "teşekkür edilmemektedir.", None))
parts.append(p("ÖZET", "Heading1"))
parts.append(p("Amaç: Biçim denetiminin uçtan uca sınanması. Yöntem: Bilinçli hatalar ekilmiş "
               "sentetik belge. Bulgular: Raporla karşılaştırılacaktır.", None))
front_sect = _sect_pr(rules, "lowerRoman", footer_rel="rId2", header_rel=None)
parts.append(f"<w:p><w:pPr>{front_sect}</w:pPr></w:p>")

# GİRİŞ
parts.append(p("GİRİŞ", "Heading1"))
parts.append(p(GOVDE, None))
# E1: satır aralığı 1.0
parts.append(p("HATA-1 " + GOVDE, None, ppr='<w:spacing w:line="240" w:lineRule="auto"/>'))
planted(1, "body.line_spacing", "GİRİŞ 2. paragraf", True)

# GENEL BİLGİLER
parts.append(p("GENEL BİLGİLER", "Heading1"))
parts.append(p("Tanım ve Sınıflama", "Heading2"))
parts.append(p(GOVDE, None))
# E2: yanlış yazı tipi
parts.append(p("HATA-2 " + GOVDE, None,
               rpr='<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/>'))
planted(2, "body.font", "GENEL BİLGİLER", True)
# E8: title case bozuk h2 (uyarı, düzeltilemez)
parts.append(p("Hastaların demografik özellikleri", "Heading2"))
planted(8, "heading_2.case", "GENEL BİLGİLER 2. alt başlık", False)
parts.append(p(GOVDE, None))
parts.append(p("Epidemiyolojik veriler", "Heading3"))
parts.append(p(GOVDE, None))

# GEREÇ VE YÖNTEM
parts.append(p("GEREÇ VE YÖNTEM", "Heading1"))
# E7: kalın olmayan h2
parts.append(p("Çalışma Tasarımı", "Heading2", rpr='<w:b w:val="0"/>'))
planted(7, "heading_2.bold", "GEREÇ VE YÖNTEM ilk alt başlık", True)
# E3: sola yaslı gövde
parts.append(p("HATA-3 " + GOVDE, None, ppr='<w:jc w:val="left"/>'))
planted(3, "body.alignment", "GEREÇ VE YÖNTEM", True)
# E4: girintisiz gövde
parts.append(p("HATA-4 " + GOVDE, None, ppr='<w:ind w:firstLine="0"/>'))
planted(4, "body.first_line_indent_cm", "GEREÇ VE YÖNTEM", True)

# BULGULAR
parts.append(p("BULGULAR", "Heading1"))
parts.append(p(GOVDE, None))
parts.append(p("Tablo 1. Sentetik demografik veriler", "Caption"))
parts.append("<w:tbl><w:tblPr/><w:tblGrid><w:gridCol/></w:tblGrid><w:tr><w:tc><w:tcPr/>"
             + p("Yaş (yıl): 42 ± 7", None,
                 ppr='<w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/>'
                     '<w:jc w:val="left"/>')
             + "</w:tc></w:tr></w:tbl>")
# E5: 11 punto gövde
parts.append(p("HATA-5 " + GOVDE, None, rpr='<w:sz w:val="22"/><w:szCs w:val="22"/>'))
planted(5, "body.size_pt", "BULGULAR", True)
# E9: şekil açıklaması tek satır aralığında
parts.append(p("Şekil 1. Sentetik akış şeması", "Caption",
               ppr='<w:spacing w:line="240" w:lineRule="auto"/>'))
planted(9, "figure_caption.line_spacing", "BULGULAR şekil açıklaması", True)

# TARTIŞMA — E6: sayfa başı yapılmamış h1
parts.append(p("TARTIŞMA", "Heading1", ppr='<w:pageBreakBefore w:val="0"/>'))
planted(6, "heading_1.page_break_before", "TARTIŞMA başlığı", True)
parts.append(p(GOVDE, None))

# SONUÇLAR — bilerek eksik bölüm: SUMMARY (document.missing_section vitrini)
parts.append(p("SONUÇLAR", "Heading1"))
parts.append(p(GOVDE, None))

# KAYNAKLAR
parts.append(p("KAYNAKLAR", "Heading1"))
parts.append(p("1. Yazar A, Yazar B. Sentetik bir çalışmanın başlığı. Uydurma Dergi. "
               "2020;12(3):45-52.", "Bibliography"))
parts.append(p("2. Yazar C. Bir başka sentetik kaynak. Hayali Yayınevi; 2019.", "Bibliography"))

# Gövde bölümü — E10: sol kenar 2.5 (4 olmalı)
body_sect = _sect_pr(rules, "decimal", footer_rel="rId3", header_rel=None, start_one=True)
body_sect = body_sect.replace('w:left="2268"', 'w:left="1418"')
assert 'w:left="1418"' in body_sect
parts.append(body_sect)
planted(10, "page.margin.left", "ana metin bölümü", True)

document = (f'{XML_DECL}<w:document xmlns:w="{W_NS}" xmlns:r="{OFFICE_REL}">'
            f"<w:body>{''.join(parts)}</w:body></w:document>")

# Altbilgiler: ön bölümde süslü numara (E11, düzeltilemez), gövdede temiz sağda
PAGE_FIELD = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              "<w:r><w:t>1</w:t></w:r>"
              '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
footer_front = (f'{XML_DECL}<w:ftr xmlns:w="{W_NS}"><w:p><w:pPr><w:jc w:val="right"/></w:pPr>'
                f'<w:r><w:t xml:space="preserve">- </w:t></w:r>{PAGE_FIELD}'
                f'<w:r><w:t xml:space="preserve"> -</w:t></w:r></w:p></w:ftr>')
planted(11, "page_numbering.decoration", "ön bölüm altbilgisi", False)
planted(12, "document.missing_section", "SUMMARY bölümü bilerek yok", False)
footer_body = (f'{XML_DECL}<w:ftr xmlns:w="{W_NS}"><w:p><w:pPr><w:jc w:val="right"/></w:pPr>'
               f"{PAGE_FIELD}</w:p></w:ftr>")

doc_rels = (f'{XML_DECL}<Relationships xmlns="{REL_NS}">'
            f'<Relationship Id="rId1" Type="{OFFICE_REL}/styles" Target="styles.xml"/>'
            f'<Relationship Id="rId2" Type="{OFFICE_REL}/footer" Target="footer1.xml"/>'
            f'<Relationship Id="rId3" Type="{OFFICE_REL}/footer" Target="footer2.xml"/>'
            "</Relationships>")
ct_base = "application/vnd.openxmlformats-officedocument.wordprocessingml"
content_types = (
    f'{XML_DECL}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType='
    '"application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    f'<Override PartName="/word/document.xml" ContentType="{ct_base}.document.main+xml"/>'
    f'<Override PartName="/word/styles.xml" ContentType="{ct_base}.styles+xml"/>'
    f'<Override PartName="/word/footer1.xml" ContentType="{ct_base}.footer+xml"/>'
    f'<Override PartName="/word/footer2.xml" ContentType="{ct_base}.footer+xml"/>'
    "</Types>")
root_rels = (f'{XML_DECL}<Relationships xmlns="{REL_NS}">'
             f'<Relationship Id="rId1" Type="{OFFICE_REL}/officeDocument" '
             'Target="word/document.xml"/></Relationships>')
files = {
    "[Content_Types].xml": content_types,
    "_rels/.rels": root_rels,
    "word/document.xml": document,
    "word/_rels/document.xml.rels": doc_rels,
    "word/styles.xml": _styles_xml(rules),
    "word/footer1.xml": footer_front,
    "word/footer2.xml": footer_body,
}
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
    for name, content in files.items():
        zf.writestr(name, content.encode("utf-8"))
(OUT / "ornek-tez.docx").write_bytes(buf.getvalue())
print(json.dumps(manifest, ensure_ascii=False))
print(f"yazıldı: {OUT/'ornek-tez.docx'} ({len(buf.getvalue())} bayt), "
      f"ekilen hata: {len(manifest)}")
