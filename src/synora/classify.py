"""A4 — Kural tabanlı rol sınıflandırıcı.

Girdi yalnızca ParaFeatures'tır: bu fonksiyon tez metnine erişemez. İleride yerel bir model
ya da LLM aynı imzayla bunun yerine (ya da yanına) konabilir.

Güven değerleri: 1.0 yapısal kesinlik · 0.9 açık stil · 0.8 güçlü desen · 0.6–0.7 sezgisel.
Emin olunamayan durumlar UNKNOWN olur; denetlenmez, raporda "rolü belirsiz" diye çıkar.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from synora.features import Keyword, NumberPrefix, NumFormat, ParaFeatures, StyleKind
from synora.model import Alignment, Role, Story

MAX_HEADING_WORDS = 15
MAX_CAPTION_WORDS = 40


class RoleDecision(BaseModel):
    """Her sınıflandırıcının (LLM dahil) döndürebileceği tek şey."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Role
    confidence: float = Field(ge=0.0, le=1.0)


def _d(role: Role, confidence: float) -> RoleDecision:
    return RoleDecision(role=role, confidence=confidence)


UNKNOWN = _d(Role.UNKNOWN, 0.0)

_STYLE_ROLES = {
    StyleKind.HEADING_1: Role.HEADING_1,
    StyleKind.HEADING_2: Role.HEADING_2,
    StyleKind.HEADING_3: Role.HEADING_3,
    StyleKind.TITLE: Role.TITLE,
    StyleKind.QUOTE: Role.BLOCK_QUOTE,
    StyleKind.BIBLIOGRAPHY: Role.REFERENCE_ENTRY,
    StyleKind.FOOTNOTE: Role.FOOTNOTE,
}
_PREFIX_HEADINGS = {
    NumberPrefix.ARABIC_1: Role.HEADING_1,
    NumberPrefix.ARABIC_2: Role.HEADING_2,
    NumberPrefix.ARABIC_3: Role.HEADING_3,
}
_LEVEL_HEADINGS = {0: Role.HEADING_1, 1: Role.HEADING_2, 2: Role.HEADING_3}


def classify(f: ParaFeatures) -> RoleDecision:
    structural = _structural(f)
    if structural is not None:
        return structural

    # Açık stil sinyalleri
    if f.style_kind is StyleKind.TOC or f.has_toc_field:
        return _d(Role.TOC_ENTRY, 0.9)
    if f.style_kind in _STYLE_ROLES:
        return _d(_STYLE_ROLES[f.style_kind], 0.9)
    # 4. ve daha alt düzey başlıklar için kural yok: 1. düzey sanılmasın, denetlenmesin.
    if f.style_kind is StyleKind.HEADING_OTHER or (
        f.outline_level is not None and f.outline_level not in _LEVEL_HEADINGS
    ):
        return UNKNOWN
    if f.outline_level is not None and f.outline_level in _LEVEL_HEADINGS:
        return _d(_LEVEL_HEADINGS[f.outline_level], 0.85)
    if f.style_kind is StyleKind.CAPTION or f.has_seq_field:
        return _d(_caption_role(f), 0.85)

    # Kapak: ilk sayfadaki kısa satırlar (üniversite adı, "T.C.", danışman, tarih).
    # Kapak kuralları kural setine eklenene kadar denetlenmez.
    if (
        f.on_first_page
        and f.word_count <= 12
        and f.keyword not in (Keyword.SECTION_TITLE, Keyword.FRONT_TITLE)
        and (
            f.alignment in (Alignment.CENTER, Alignment.RIGHT)
            or not f.ends_with_sentence_punct
        )
    ):
        return _d(Role.COVER, 0.8)
    # İç kapak, onay ve beyan sayfaları: ilk ön sayfa başlığından (ÖZET, İÇİNDEKİLER…) önce.
    if f.on_cover_pages:
        return _d(Role.COVER, 0.7)

    # Desen sinyalleri
    if f.toc_like and f.word_count <= 25:
        return _d(Role.TOC_ENTRY, 0.8)
    if f.keyword in (Keyword.FIGURE_CAPTION, Keyword.TABLE_CAPTION) and (
        f.word_count <= MAX_CAPTION_WORDS
    ):
        return _d(_caption_role(f), 0.8)
    heading = _unstyled_heading(f)
    if heading is not None:
        return heading
    if f.in_references_section:
        return _d(Role.REFERENCE_ENTRY, 0.85 if f.reference_like else 0.65)
    if f.style_kind is StyleKind.LIST or f.numbering_format is NumFormat.BULLET or (
        f.number_prefix in (NumberPrefix.BULLET, NumberPrefix.LETTER)
    ):
        return _d(Role.LIST_ITEM, 0.75)
    if f.numbering_format in (NumFormat.DECIMAL, NumFormat.LETTER, NumFormat.ROMAN):
        return _d(Role.LIST_ITEM, 0.6)

    # Kısa, ortalanmış ya da sağa yaslı satırlar (imza, tarih, onay satırları): gövde değil.
    if f.word_count <= 12 and f.alignment in (Alignment.CENTER, Alignment.RIGHT):
        return UNKNOWN
    # Girintili, küçük puntolu uzun paragraf: blok alıntı
    if (
        f.indent_left_cm is not None and f.indent_left_cm >= 0.9
        and f.word_count >= 25
        and f.size_ratio is not None and f.size_ratio < 1.0
    ):
        return _d(Role.BLOCK_QUOTE, 0.6)
    if f.in_front_matter:
        # Önsöz/özet metni: kılavuzlar burada gövdeden farklı kurallara izin verebilir
        # (ör. ZBEÜ: önsöz tek satır aralıklı yazılabilir).
        return _d(Role.FRONT_MATTER, 0.7)
    return _d(Role.BODY, 0.6 if f.style_kind is StyleKind.CUSTOM else 0.7)


def _structural(f: ParaFeatures) -> RoleDecision | None:
    if f.story is Story.FOOTNOTE:
        return _d(Role.FOOTNOTE, 1.0)
    if f.story is Story.ENDNOTE:
        return _d(Role.ENDNOTE, 1.0)
    if f.story in (Story.HEADER, Story.FOOTER):
        return _d(Role.HEADER_FOOTER, 1.0)
    if f.char_count == 0:
        return _d(Role.EMPTY, 1.0)
    if f.in_textbox:
        return _d(Role.TEXTBOX, 1.0)
    if f.in_table:
        return _d(Role.TABLE_CELL, 1.0)
    return None


def _caption_role(f: ParaFeatures) -> Role:
    if f.keyword is Keyword.TABLE_CAPTION:
        return Role.TABLE_CAPTION
    if f.keyword is Keyword.FIGURE_CAPTION:
        return Role.FIGURE_CAPTION
    return Role.TABLE_CAPTION if f.next_is_table else Role.FIGURE_CAPTION


def _unstyled_heading(f: ParaFeatures) -> RoleDecision | None:
    """Stil kullanılmadan elle biçimlenmiş başlıklar: kısa, nokta ile bitmeyen,
    gövdeden ayrışan (kalın / büyük harf / büyük punto) satırlar."""
    if f.word_count > MAX_HEADING_WORDS or f.ends_with_sentence_punct or f.has_citation:
        return None
    caps = f.upper_ratio >= 0.8
    emphasized = f.bold or caps or (f.size_ratio is not None and f.size_ratio >= 1.1)
    if f.keyword in (Keyword.SECTION_TITLE, Keyword.REFERENCES_TITLE, Keyword.CHAPTER,
                     Keyword.FRONT_TITLE):
        return _d(Role.HEADING_1, 0.85 if emphasized or f.starts_page else 0.7)
    if not emphasized:
        return None
    if f.number_prefix in _PREFIX_HEADINGS:
        return _d(_PREFIX_HEADINGS[f.number_prefix], 0.8)
    if f.numbering_format is NumFormat.DECIMAL and f.numbering_level in _LEVEL_HEADINGS:
        return _d(_LEVEL_HEADINGS[f.numbering_level], 0.75)
    # Sayfa ortasında yalnızca büyük harfli ortalı satır (ör. ÖZET sayfasındaki tez adı) başlık
    # sayılmaz; kalın ya da büyük puntolu olması gerekir.
    stands_out = f.bold or (f.size_ratio is not None and f.size_ratio >= 1.1)
    if caps and (f.starts_page or (f.alignment is Alignment.CENTER and stands_out)):
        return _d(Role.HEADING_1, 0.75)
    # Kalın ama numarasız, karışık harfli kısa satır: 2. mi 3. düzey mi, ara başlık mı?
    # Tahmin etmek yerine belirsiz bırak.
    return UNKNOWN
