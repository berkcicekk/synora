"""Rol sınıflandırma için etiketli sentetik tez derlemi.

Her örnek (paragraf XML'i, beklenen rol). Üç "öğrenci alışkanlığı" taklit edilir:
stilleri doğru kullanan, hiç stil kullanmayıp elle biçimlendiren ve ikisini karıştıran.
Metinler uydurmadır; gerçek tezlerden alınmamıştır.
"""

from __future__ import annotations

import random

from builders import p, r, style, styles_xml

from synora.model import Role

TNR = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/><w:sz w:val="24"/>'
STYLES = styles_xml(
    defaults_rpr=TNR,
    styles=(
        style("Normal", default=True, name="Normal",
              ppr='<w:jc w:val="both"/><w:spacing w:line="360"/><w:ind w:firstLine="709"/>')
        + style("Heading1", based_on="Normal", name="heading 1", rpr='<w:b/><w:sz w:val="28"/>')
        + style("Heading2", based_on="Normal", name="heading 2", rpr="<w:b/>")
        + style("Heading3", based_on="Normal", name="heading 3", rpr="<w:b/><w:i/>")
        + style("Caption", based_on="Normal", name="caption", rpr='<w:sz w:val="20"/>')
        + style("TOC1", based_on="Normal", name="toc 1")
        + style("ListParagraph", based_on="Normal", name="List Paragraph")
        + style("Quote", based_on="Normal", name="Quote", rpr="<w:i/>")
        + style("Bibliography", based_on="Normal", name="Bibliography")
    ),
)

SENTENCES = [
    "Bu çalışmada öğrencilerin akademik yazma becerileri farklı açılardan incelenmiştir.",
    "Elde edilen bulgular literatürdeki önceki çalışmalarla büyük ölçüde örtüşmektedir.",
    "Araştırmanın evrenini Zonguldak ilindeki ortaokul öğretmenleri oluşturmaktadır.",
    "Veriler yarı yapılandırılmış görüşme formu aracılığıyla toplanmıştır.",
    "Yılmaz (2019) benzer bir örneklemde farklı sonuçlara ulaştığını belirtmiştir.",
    "Bu bulgu öğretim ortamının öğrenme sürecine etkisini açıkça göstermektedir (Demir, 2021).",
    "Şekil 3.1'de görüldüğü gibi model üç temel bileşenden oluşmaktadır.",
    "Tablo 2.4’te katılımcıların demografik özellikleri ayrıntılı olarak verilmiştir.",
    "Şekil 2.1 ve Şekil 2.2 birlikte değerlendirildiğinde eğilim açıkça görülmektedir.",
    "Ölçeğin güvenirlik katsayısı 0,87 olarak hesaplanmış ve yeterli bulunmuştur [12].",
    "Sonuç olarak önerilen yaklaşımın uygulanabilir olduğu değerlendirilmektedir.",
    "2020 yılında yapılan ölçümler kontrol grubunda anlamlı bir fark göstermemiştir.",
]
QUOTE = ("Bilim, insanlığın ortak mirasıdır ve her kuşak bu mirası bir sonrakine daha zengin "
         "bırakmakla yükümlüdür; bu nedenle araştırmacının sorumluluğu yalnızca kendi "
         "dönemine değil geleceğe de uzanır.")
REFERENCES = [
    "Akın, A. ve Kaya, B. (2018). Eğitimde ölçme ve değerlendirme. Ankara: Pegem Akademi.",
    "Demir, C. (2021). Öğretmen algıları üzerine nitel bir çalışma. Eğitim ve Bilim, 46(2), "
    "115-134.",
    "Smith, J. A., & Brown, K. (2015). Research methods in education. London: Routledge.",
    "Yılmaz, E. (2019). Akademik yazma becerileri. Yayımlanmamış doktora tezi, Ankara.",
]
TOC_LINES = ["GİRİŞ\t1", "1.1 Araştırmanın Amacı\t3", "YÖNTEM\t12", "KAYNAKLAR\t48"]

H1_TITLES = ["GİRİŞ", "KAVRAMSAL ÇERÇEVE", "YÖNTEM", "BULGULAR", "TARTIŞMA", "SONUÇ VE ÖNERİLER"]
H2_TITLES = ["Araştırmanın Amacı", "Araştırmanın Önemi", "Evren ve Örneklem",
             "Veri Toplama Araçları", "Verilerin Analizi"]
H3_TITLES = ["Kişisel Bilgi Formu", "Görüşme Formu", "Nitel Veri Analizi"]

Sample = tuple[str, Role]


def body(rng: random.Random) -> Sample:
    text = " ".join(rng.sample(SENTENCES, rng.randint(2, 4)))
    return p(text), Role.BODY


def styled(rng: random.Random, ch: int) -> list[Sample]:
    out: list[Sample] = [
        (p(f"{ch}. {rng.choice(H1_TITLES)}", ppr='<w:pStyle w:val="Heading1"/>'), Role.HEADING_1),
        body(rng),
        (p(f"{ch}.1 {rng.choice(H2_TITLES)}", ppr='<w:pStyle w:val="Heading2"/>'),
         Role.HEADING_2),
        body(rng),
        (p(f"{ch}.1.1 {rng.choice(H3_TITLES)}", ppr='<w:pStyle w:val="Heading3"/>'),
         Role.HEADING_3),
        body(rng),
        (p(f"Şekil {ch}.1 Araştırma modeli", ppr='<w:pStyle w:val="Caption"/>'),
         Role.FIGURE_CAPTION),
        (p(f"Tablo {ch}.1 Katılımcı dağılımı", ppr='<w:pStyle w:val="Caption"/>'),
         Role.TABLE_CAPTION),
        (_table(), Role.TABLE_CELL),
        (p("Birinci madde açıklaması", ppr='<w:pStyle w:val="ListParagraph"/>'),
         Role.LIST_ITEM),
        (p(QUOTE, ppr='<w:pStyle w:val="Quote"/>'), Role.BLOCK_QUOTE),
        body(rng),
    ]
    return out


def manual(rng: random.Random, ch: int) -> list[Sample]:
    """Hiç stil yok: her şey Normal stilde elle biçimlenmiş."""
    center = '<w:jc w:val="center"/><w:ind w:firstLine="0"/>'
    left = '<w:jc w:val="left"/><w:ind w:firstLine="0"/>'
    title = rng.choice(H1_TITLES)
    out: list[Sample] = [
        (p('<w:r><w:br w:type="page"/></w:r>'), Role.EMPTY),
        (p(r(f"{ch}. {title}", rpr='<w:b/><w:sz w:val="28"/>'), ppr=center), Role.HEADING_1),
        body(rng),
        (p(r(f"{ch}.2. {rng.choice(H2_TITLES)}", rpr="<w:b/>"), ppr=left), Role.HEADING_2),
        body(rng),
        body(rng),
        (p(r(f"{ch}.2.1. {rng.choice(H3_TITLES)}", rpr="<w:b/><w:i/>"), ppr=left),
         Role.HEADING_3),
        body(rng),
        (p(f"Şekil {ch}.2. Kavramsal model", ppr=center), Role.FIGURE_CAPTION),
        (p(f"Tablo {ch}.2: Ölçek puanlarının dağılımı", ppr=left), Role.TABLE_CAPTION),
        (_table(), Role.TABLE_CELL),
        (p("• Öğretmenlerin görüşleri alınmıştır."), Role.LIST_ITEM),
        (p("a) Nitel verilerin çözümlenmesi"), Role.LIST_ITEM),
        body(rng),
    ]
    return out


def mixed(rng: random.Random, ch: int) -> list[Sample]:
    """Bölüm başlığı büyük harf + sayfa sonu, alt başlıklar stilsiz, bazı başlıklar stilli."""
    center = '<w:jc w:val="center"/><w:ind w:firstLine="0"/>'
    out: list[Sample] = [
        (p(r(rng.choice(H1_TITLES), rpr="<w:b/>"), ppr=center + "<w:pageBreakBefore/>"),
         Role.HEADING_1),
        body(rng),
        (p(f"{ch}.3 {rng.choice(H2_TITLES)}", ppr='<w:pStyle w:val="Heading2"/>'),
         Role.HEADING_2),
        body(rng),
        (p(r(f"{ch}.3.2 {rng.choice(H3_TITLES)}", rpr="<w:b/>")), Role.HEADING_3),
        body(rng),
        (p(r(f"Şekil {ch}.3. Uygulama süreci")), Role.FIGURE_CAPTION),
        body(rng),
        # Belirsiz: kalın, numarasız, karışık harfli kısa satır
        (p(r("Araştırmanın sınırlılıkları", rpr="<w:b/>")), Role.UNKNOWN),
        body(rng),
    ]
    return out


def front_matter(rng: random.Random) -> list[Sample]:
    center = '<w:jc w:val="center"/><w:ind w:firstLine="0"/>'
    return [
        (p(r("T.C.", rpr="<w:b/>"), ppr=center), Role.COVER),
        (p(r("ZONGULDAK BÜLENT ECEVİT ÜNİVERSİTESİ", rpr="<w:b/>"), ppr=center), Role.COVER),
        (p("Danışman: Doç. Dr. Ayşe KARA", ppr=center), Role.COVER),
        (p("Zonguldak, 2026", ppr=center), Role.COVER),
        (p(r("ÖZET", rpr="<w:b/>"), ppr=center + "<w:pageBreakBefore/>"), Role.HEADING_1),
        body(rng),
        (p(r("İÇİNDEKİLER", rpr="<w:b/>"), ppr=center + "<w:pageBreakBefore/>"), Role.HEADING_1),
        *[(p(line, ppr='<w:pStyle w:val="TOC1"/>'), Role.TOC_ENTRY) for line in TOC_LINES[:2]],
        *[(p(line), Role.TOC_ENTRY) for line in TOC_LINES[2:]],
    ]


def back_matter(styled_refs: bool) -> list[Sample]:
    center = '<w:jc w:val="center"/><w:ind w:firstLine="0"/>'
    hanging = '<w:ind w:left="709" w:hanging="709"/><w:spacing w:line="240"/>'
    ref_ppr = '<w:pStyle w:val="Bibliography"/>' if styled_refs else hanging
    return [
        (p(r("KAYNAKLAR", rpr="<w:b/>"), ppr=center + "<w:pageBreakBefore/>"), Role.HEADING_1),
        *[(p(ref, ppr=ref_ppr), Role.REFERENCE_ENTRY) for ref in REFERENCES],
        (p(r("EKLER", rpr="<w:b/>"), ppr=center + "<w:pageBreakBefore/>"), Role.HEADING_1),
        body(random.Random(0)),
    ]


def _table() -> str:
    cell = p("Değer", ppr='<w:ind w:firstLine="0"/>')
    return f"<w:tbl><w:tr><w:tc>{cell}</w:tc><w:tc>{cell}</w:tc></w:tr></w:tbl>"


def build(seed: int) -> list[Sample]:
    rng = random.Random(seed)
    samples = front_matter(rng)
    for ch in range(1, 5):
        habit = rng.choice([styled, manual, mixed])
        samples.extend(habit(rng, ch))
    samples.extend(back_matter(styled_refs=rng.random() < 0.5))
    return samples
