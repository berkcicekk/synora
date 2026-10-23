"""Bölüm bağlamı: gövde olmayan bölümler gövde kuralıyla denetlenmez (doğruluk testi, 2026-10-23).

39 resmî şablonda temiz belgede medyan 84 bulgu vardı; gövde bulgularının en az %37'si kısaltma
listesi, kaynakça, onay/beyan sayfası ve özgeçmişteydi. Nedenler: başlık adları birebir listede
aranıyordu ("SİMGELER DİZİNİ", "KAYNAKLAR/REFERENCES" tanınmıyordu), onay sayfaları ve özgeçmiş
için ayrı işlem yoktu, sayfa tepesindeki tez adı bloğu ve iki satırlı bölüm başlığı yanlış
okunuyordu. Desenler sentetik olarak yeniden üretilir; şablonlar teste konmaz.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from builders import p, r
from thesis import BODY_TEXT, front_matter, h1, main_matter, sect, thesis

from synora.check import CheckResult, check
from synora.features import Keyword, keyword
from synora.ingest import open_docx
from synora.model import Role
from synora.parse import parse_package
from synora.roles import assign_roles
from synora.ruleset import load_ruleset

RULES = load_ruleset(Path(__file__).resolve().parents[2] / "rulesets" / "example.yaml")
BRK = p('<w:r><w:br w:type="page"/></w:r>')
# Kılavuza (1,5 satır, girinti, iki yana yaslı) aykırı: gövde sanılırsa bulgu üretir.
SINGLE = ('<w:spacing w:line="240" w:lineRule="auto" w:after="0"/>'
          '<w:ind w:firstLine="0"/><w:jc w:val="left"/>')
NO_BREAK_H1 = '<w:pStyle w:val="Heading1"/><w:pageBreakBefore w:val="0"/>'
CENTER = '<w:jc w:val="center"/><w:ind w:firstLine="0"/>'


def run(data: bytes) -> CheckResult:
    return check(parse_package(open_docx(data)), RULES)


def role_of(data: bytes) -> dict[str, Role]:
    doc = parse_package(open_docx(data))
    decided = assign_roles(doc)
    return {p.text: decided[p.para_id].role for p in doc.body() if p.text.strip()}


def body_findings_on(data: bytes, texts: tuple[str, ...]) -> list[str]:
    doc = parse_package(open_docx(data))
    ids = {p.para_id for p in doc.body() if p.text in texts}
    return [f.rule_id for f in run(data).findings if f.para_id in ids]


def flat(text: str) -> str:
    return p(text, ppr=SINGLE)


# --- Başlık tanıma ---------------------------------------------------------------------------


@pytest.mark.parametrize("title", [
    "SİMGELER DİZİNİ", "KISALTMA LİSTESİ", "KISALTMALAR VE SİMGELER DİZİNİ",
    "SEMBOLLER VE KISALTMALAR DİZİNİ", "SİMGE VE KISALTMA LİSTESİ", "SİMGE LİSTESİ",
    "Simgeler ve Kısaltmalar", "KISALTMALAR (Varsa) (Alfabetik sıra ile verilmelidir)",
    "KISALTMALAR/ABBREVIATIONS", "SEMBOLLER/SYMBOLS", "LIST OF ABBREVIATIONS",
])
def test_symbol_and_abbreviation_lists_are_front_titles(title: str) -> None:
    assert keyword(title) is Keyword.FRONT_TITLE


@pytest.mark.parametrize("title", ["KAYNAKLAR/REFERENCES", "Kaynakça", "KAYNAKÇA 1"])
def test_reference_title_variants(title: str) -> None:
    assert keyword(title) is Keyword.REFERENCES_TITLE


@pytest.mark.parametrize("line", ["KAYNAKÇA\t108", "KAYNAKLAR ............ 45", "ÖZGEÇMİŞ\t112"])
def test_table_of_contents_lines_are_not_titles(line: str) -> None:
    # İçindekiler satırı başlık sanılırsa kaynakça bölümü içindekiler sayfasında başlar.
    assert keyword(line) is Keyword.NONE


@pytest.mark.parametrize("title", [
    "TEZ ONAYI", "KABUL VE ONAY TUTANAĞI", "KABUL VE ONAY", "ONAY", "APPROVAL",
    "TEZ ÖZGÜNLÜK BEYANI", "İNTİHAL BEYANI", "KILAVUZA UYGUNLUK BEYANI", "TAAHHÜTNAME",
    "ETİK KURUL ONAYI (yoksa silinir)",
])
def test_approval_and_declaration_titles(title: str) -> None:
    assert keyword(title) is Keyword.APPROVAL_TITLE


@pytest.mark.parametrize(("text", "expected"), [
    ("ETİK BEYAN", Keyword.FRONT_TITLE),  # önceki davranış korunur
    ("GİRİŞ", Keyword.SECTION_TITLE),
    ("Bu tezin onayı etik kuruldan alınmıştır.", Keyword.NONE),  # cümle, başlık değil
    # Asıl metindeki madde satırı: onay başlığı sanılınca altındaki şekil başlıklarını yutuyordu
    # (kastamonu-fbe). Onay/beyan başlıkları büyük harfle yazılır; küçük harfli satır başlık değil.
    ("Nihai intihal raporu", Keyword.NONE),
    ("Etik Kurul Değerlendirme Sonucu", Keyword.NONE),
])
def test_title_recognition_guards(text: str, expected: Keyword) -> None:
    assert keyword(text) is expected


# --- Gövde olmayan bölümler -----------------------------------------------------------------

ABBR = ("PID: Proportional Integral Derivative", "MRG : Manyetik Rezonans Görüntüleme",
        "ADL Activities of Daily Life")


def test_abbreviation_list_is_not_checked_as_body() -> None:
    front = (h1("ÖNSÖZ") + p(BODY_TEXT) + h1("SİMGELER VE KISALTMALAR LİSTESİ")
             + "".join(flat(t) for t in ABBR) + p(BODY_TEXT, ppr=sect("lowerRoman")))
    data = thesis(front + main_matter())
    roles = role_of(data)
    assert all(roles[t] is not Role.BODY for t in ABBR), roles
    assert body_findings_on(data, ABBR) == []


REFS = ("Liu, J.X., Liang, Z. (2008) Landfill leachate treatment with membranes. Water Res. 42.",
        "Albayrak, A., Akhan, A. U. (2019) Enerji ithalatı üzerine bir inceleme. Ankara.")


def test_bilingual_references_heading_starts_reference_section() -> None:
    data = thesis(front_matter() + main_matter(extra=h1("KAYNAKLAR/REFERENCES")
                                               + "".join(flat(t) for t in REFS)))
    roles = role_of(data)
    assert all(roles[t] is Role.REFERENCE_ENTRY for t in REFS), roles
    assert not [f for f in body_findings_on(data, REFS) if f.startswith("body.")]


APPROVAL = ("Dr. Adı SOYADI, Üye", "Doç. Dr. Adı SOYADI (Danışman)",
            "Bu tez jürimiz tarafından yüksek lisans tezi olarak kabul edilmiştir.")


def test_approval_page_lines_are_cover_not_body() -> None:
    # Onay başlığı Başlık 1 stilinde olsa bile kapak sayfaları sürer (ön sayfa başlamaz).
    cover = p(r("ÜNİVERSİTE ADI", rpr="<w:b/>"), ppr=CENTER) + BRK
    approval = h1("TEZ ONAYI") + "".join(flat(t) for t in APPROVAL) + BRK
    data = thesis(cover + approval + front_matter() + main_matter())
    roles = role_of(data)
    assert roles["TEZ ONAYI"] is Role.COVER
    assert all(roles[t] is Role.COVER for t in APPROVAL), roles
    assert roles["ÖNSÖZ"] is Role.HEADING_1  # ön sayfalar yine tanınır
    assert body_findings_on(data, (*APPROVAL, "TEZ ONAYI")) == []


CV = ("Doğum Yılı: 1990", "Yabancı Diller: İngilizce (Düzey: İleri)",
      "Lisans eğitimini Ankara Üniversitesi Fen Fakültesi Kimya Bölümünde tamamladı.")


def test_curriculum_vitae_is_not_checked_as_body() -> None:
    data = thesis(front_matter() + main_matter(extra=h1("ÖZGEÇMİŞ") + "".join(flat(t) for t in CV)))
    roles = role_of(data)
    assert roles["ÖZGEÇMİŞ"] is Role.HEADING_1  # başlığın kendisi denetlenir
    assert all(roles[t] is Role.COVER for t in CV), roles
    assert body_findings_on(data, CV) == []


def test_real_body_text_is_still_checked() -> None:
    # Koruma: asıl metindeki tek aralıklı paragraf hâlâ gövde bulgusu üretir.
    data = thesis(front_matter() + main_matter(extra=flat(BODY_TEXT + " Ek cümle.")))
    assert "body.line_spacing" in body_findings_on(data, (BODY_TEXT + " Ek cümle.",))


# --- Sayfa tepesindeki başlık bloğu (ÖZET/ABSTRACT sayfasında tez adı, yazar) -----------------

TITLE_BLOCK = ("TÜRKİYE'NİN ENERJİ İTHALATINDA YENİLENEBİLİR KAYNAKLAR", "Ad SOYAD")


def test_title_block_above_front_heading_is_not_a_heading() -> None:
    # Gerçek desen: sayfa tez adıyla açılır, ÖZET başlığı aynı sayfada altında (sayfa sonu yok).
    block = BRK + "".join(p(r(t, rpr="<w:caps/>" if i == 0 else ""), ppr=CENTER)
                          for i, t in enumerate(TITLE_BLOCK))
    ozet = p("ÖZET", ppr=NO_BREAK_H1)
    front = h1("ÖNSÖZ") + p(BODY_TEXT) + block + ozet + p(BODY_TEXT, ppr=sect("lowerRoman"))
    data = thesis(front + main_matter())
    roles = role_of(data)
    assert all(roles[t] not in (Role.HEADING_1, Role.BODY) for t in TITLE_BLOCK), roles
    assert body_findings_on(data, TITLE_BLOCK) == []
    # Sayfayı başlık bloğu açtığı için ÖZET de sayfa başında sayılır.
    assert "heading_1.page_break_before" not in body_findings_on(data, ("ÖZET",))


# --- İki satırlı bölüm başlığı ----------------------------------------------------------------

def test_second_line_of_chapter_heading_shares_the_page_start() -> None:
    two_line = (h1("İKİNCİ BÖLÜM")
                + p("KURAMSAL ÇERÇEVE", ppr=NO_BREAK_H1)
                + p(BODY_TEXT))
    result = run(thesis(front_matter() + main_matter(extra=two_line)))
    assert "heading_1.page_break_before" not in {f.rule_id for f in result.findings}


def test_heading_after_body_text_still_needs_page_break() -> None:
    # Koruma: önceki satır başlık değil gövde ise "yeni sayfada değil" uyarısı sürer.
    lone = p(BODY_TEXT) + p("YÖNTEM", ppr=NO_BREAK_H1)
    result = run(thesis(front_matter() + main_matter(extra=lone)))
    assert "heading_1.page_break_before" in {f.rule_id for f in result.findings}


def test_appendix_label_is_not_reinterpreted() -> None:
    # Gerileme koruması: "KAYNAKÇA 1" kuralı genel olunca "Ek 1" bölüm başlığı sanılıyordu.
    assert keyword("Ek 1") is Keyword.NONE


def test_cv_ends_at_next_section_heading_after_page_break_and_blank_line() -> None:
    # Özgeçmişten sonra gelen bölüm (sayfa sonu + boş satır + büyük harfli başlık) yutulmamalı
    # (beykent-lee "TOPLUMSAL KATKI").
    after = (BRK + p("") + p(r("TOPLUMSAL KATKI", rpr="<w:b/>"), ppr=CENTER)
             + flat(BODY_TEXT + " Katkı."))
    data = thesis(front_matter() + main_matter(extra=h1("ÖZGEÇMİŞ") + flat(CV[0]) + after))
    roles = role_of(data)
    assert roles[CV[0]] is Role.COVER
    assert roles["TOPLUMSAL KATKI"] is not Role.COVER
    assert roles[BODY_TEXT + " Katkı."] is not Role.COVER


def test_cv_ends_at_bold_caps_section_title_on_same_page() -> None:
    # Gerçek desen (beykent-lee): "TOPLUMSAL KATKI" bölümü özgeçmişten sonra, sayfa sonu olmadan
    # aynı sayfada başlar; bilinen bölüm adı olarak özgeçmişi bitirir.
    label = p(r("Öğrencinin Adı SOYADI", rpr="<w:b/>"), ppr=SINGLE)
    nxt = p(r("TOPLUMSAL KATKI", rpr="<w:b/>"), ppr=SINGLE) + flat(BODY_TEXT + " Katkı.")
    data = thesis(front_matter() + main_matter(extra=h1("ÖZGEÇMİŞ") + flat(CV[0]) + label + nxt))
    roles = role_of(data)
    assert roles[CV[0]] is Role.COVER and roles["Öğrencinin Adı SOYADI"] is Role.COVER
    assert roles["TOPLUMSAL KATKI"] is not Role.COVER
    assert roles[BODY_TEXT + " Katkı."] is not Role.COVER


def test_cv_subheadings_stay_inside_cv() -> None:
    # Koruma: "kalın + büyük harf satır bölümü bitirir" genellemesi 39 şablonun 11'inde özgeçmişi
    # kendi alt başlığında ("KİŞİSEL BİLGİLER", "ÖĞRENİM DURUMU:") bitirip yanlış alarmları geri
    # getiriyordu.
    sub = p(r("KİŞİSEL BİLGİLER", rpr="<w:b/>"), ppr=SINGLE)
    cv = h1("ÖZGEÇMİŞ") + sub + "".join(flat(c) for c in CV)
    data = thesis(front_matter() + main_matter(extra=cv))
    roles = role_of(data)
    assert all(roles[c] is Role.COVER for c in CV), roles
