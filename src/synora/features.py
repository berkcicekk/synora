"""ParaFeatures: sınıflandırıcının (kural tabanlı, yerel model ya da LLM) gördüğü TEK girdi.

Metin bu modülde, sunucu içinde bir kez okunur ve yalnızca sayılara, enum'lara ve
evet/hayır sinyallerine çevrilir. ParaFeatures'ta düz `str` tipli alan yoktur;
bu kural testle zorlanır (tests/unit/test_features.py).
"""

from __future__ import annotations

import re
from collections import Counter
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from synora.model import Alignment, DocModel, LineRule, Paragraph, Story

# --- Enum'lar -------------------------------------------------------------------------------


class StyleKind(StrEnum):
    NONE = "none"  # stil yok ya da varsayılan (Normal)
    HEADING_1 = "heading_1"
    HEADING_2 = "heading_2"
    HEADING_3 = "heading_3"
    HEADING_OTHER = "heading_other"
    TITLE = "title"
    CAPTION = "caption"
    TOC = "toc"
    QUOTE = "quote"
    LIST = "list"
    BIBLIOGRAPHY = "bibliography"
    FOOTNOTE = "footnote"
    CUSTOM = "custom"  # tanınmayan özel stil


class NumberPrefix(StrEnum):
    NONE = "none"
    ARABIC_1 = "arabic_1"  # "1." / "1 "
    ARABIC_2 = "arabic_2"  # "1.1"
    ARABIC_3 = "arabic_3"  # "1.1.1" ve daha derin
    ROMAN = "roman"  # "IV." / "iv)"
    LETTER = "letter"  # "a)" / "A."
    BULLET = "bullet"  # "•", "-", "–" ile başlıyor


class NumFormat(StrEnum):
    NONE = "none"
    DECIMAL = "decimal"
    ROMAN = "roman"
    LETTER = "letter"
    BULLET = "bullet"
    OTHER = "other"


class Keyword(StrEnum):
    NONE = "none"
    FIGURE_CAPTION = "figure_caption"  # "Şekil 3.1. Başlık" kalıbı
    TABLE_CAPTION = "table_caption"  # "Tablo 3.1 Başlık" kalıbı
    CHAPTER = "chapter"  # "BİRİNCİ BÖLÜM", "BÖLÜM 2"
    SECTION_TITLE = "section_title"  # ÖZET, GİRİŞ, KAYNAKÇA...
    REFERENCES_TITLE = "references_title"  # KAYNAKLAR / KAYNAKÇA / REFERENCES
    FRONT_TITLE = "front_title"  # ÖNSÖZ, ÖZET, ABSTRACT, İÇİNDEKİLER, dizinler...


class ParaFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Konum
    story: Story
    in_table: bool
    in_textbox: bool
    section_index: int | None
    relative_position: float  # gövdedeki sıra / gövde uzunluğu (0–1)
    starts_page: bool
    prev_empty: bool
    next_empty: bool
    next_is_table: bool
    in_references_section: bool
    in_front_matter: bool  # ön sayfa başlığından (ÖNSÖZ, ÖZET...) sonra, ilk bölüme kadar
    on_first_page: bool  # ilk sayfa sonundan/bölüm sonundan önce (kapak olabilir)
    on_cover_pages: bool  # ilk ön sayfa başlığından önceki birkaç sayfa (iç kapak, onay, beyan)

    # Biçim
    style_kind: StyleKind
    outline_level: int | None
    size_pt: float | None
    size_ratio: float | None  # belgenin gövde puntosuna oranı
    bold: bool
    bold_ratio: float
    italic: bool
    all_caps_format: bool
    underline: bool
    alignment: Alignment | None
    first_line_cm: float | None
    indent_left_cm: float | None
    space_before_pt: float | None
    space_after_pt: float | None
    line_multiple: float | None
    keep_next: bool
    page_break_before: bool
    numbering_format: NumFormat
    numbering_level: int | None

    # Alanlar
    has_toc_field: bool
    has_seq_field: bool

    # Şekil sinyalleri (metinden yerelde türetilmiş sayılar)
    char_count: int
    word_count: int
    upper_ratio: float  # harflerin büyük harf oranı (biçimsel büyük harf dahil)
    ends_with_sentence_punct: bool
    ends_with_colon: bool

    # Desen sinyalleri (metinden yerelde türetilmiş enum/bool)
    number_prefix: NumberPrefix
    keyword: Keyword
    toc_like: bool  # sonu sekme/nokta dizisi + sayfa numarası
    reference_like: bool  # "Soyad, A. (2020)" / "[12]" kalıbı
    has_citation: bool  # "(Yazar, 2020)" / "[3]"


# --- Desenler --------------------------------------------------------------------------------

_TR_UPPER = str.maketrans({"i": "İ", "ı": "I"})


def tr_upper(text: str) -> str:
    return text.translate(_TR_UPPER).upper()


_UPPER = "A-ZÇĞİÖŞÜ"
_NUM_RE = re.compile(r"(\d{1,3})((?:\.\d{1,3})*)\.?(?:\s|$)")
_ROMAN_RE = re.compile(r"[IVXLC]{1,6}[.)](?:\s|$)|[ivxlc]{1,6}[.)](?:\s|$)")
_LETTER_RE = re.compile(r"[a-zA-Z][.)]\s")
_BULLET_RE = re.compile(r"[•\-–—▪◦●○■□➢✓*]\s")
# Anahtar kelime büyük/küçük harf duyarsız; ardından gelen başlık metni BÜYÜK harfle başlamalı.
# Böylece "Şekil 3.1 ve Şekil 3.2..." ya da "Tablo 2.1'de..." gibi gövde cümleleri elenir.
_CAPTION_RE = re.compile(
    # Python'da "İ" küçük harfe "i̇" olarak döner; büyük yazımlar ayrıca listelenir.
    r"(?P<kw>(?i:şekil|resim|grafik|harita|fotoğraf|figure|fig\.|tablo|çizelge|table)"
    r"|ŞEKİL|ÇİZELGE|FOTOĞRAF)"
    rf"\s*(?:[{_UPPER}]-?)?\d+(?:[.\-]\d+)*\s*(?:[.:\-–—]\s*|\s+)(?=[{_UPPER}\"“(])"
)
_TABLE_KW = {"tablo", "çizelge", "table"}
_CHAPTER_RE = re.compile(
    r"(?:\d+\.\s*)?BÖLÜM\b|BÖLÜM\s+[\dIVX]+|(?:BİRİNCİ|İKİNCİ|ÜÇÜNCÜ|DÖRDÜNCÜ|BEŞİNCİ|"
    r"ALTINCI|YEDİNCİ|SEKİZİNCİ|DOKUZUNCU|ONUNCU)\s+BÖLÜM|CHAPTER\s+\d+"
)
FRONT_TITLES = frozenset({
    "ÖZET", "ABSTRACT", "SUMMARY", "ÖZ", "ÖNSÖZ", "TEŞEKKÜR", "ÖNSÖZ VE TEŞEKKÜR",
    "TEŞEKKÜR VE ÖNSÖZ", "İÇİNDEKİLER", "ŞEKİLLER LİSTESİ", "ŞEKİL LİSTESİ", "TABLOLAR LİSTESİ",
    "TABLO LİSTESİ", "ÇİZELGELER LİSTESİ", "ŞEKİLLER DİZİNİ", "TABLOLAR DİZİNİ",
    "SİMGELER VE KISALTMALAR", "SİMGELER VE KISALTMALAR DİZİNİ", "KISALTMALAR",
    "KISALTMALAR DİZİNİ", "SİMGELER", "KISALTMALAR LİSTESİ", "ETİK BEYAN",
    "BİLİMSEL ETİK BİLDİRİMİ", "ACKNOWLEDGEMENTS", "CONTENTS",
})
REFERENCE_TITLES = frozenset({"KAYNAKLAR", "KAYNAKÇA", "REFERENCES", "BIBLIOGRAPHY",
                              "YARARLANILAN KAYNAKLAR"})
_REFERENCE_END_TITLES = frozenset({"EKLER", "EK", "ÖZGEÇMİŞ", "APPENDIX", "APPENDICES",
                                   "CURRICULUM VITAE"})
SECTION_TITLES = frozenset({
    "ÖZET", "ABSTRACT", "ÖZ", "ÖNSÖZ", "TEŞEKKÜR", "İÇİNDEKİLER", "ŞEKİLLER LİSTESİ",
    "ŞEKİL LİSTESİ", "TABLOLAR LİSTESİ", "TABLO LİSTESİ", "ÇİZELGELER LİSTESİ",
    "SİMGELER VE KISALTMALAR", "KISALTMALAR", "SİMGELER", "KISALTMALAR LİSTESİ", "GİRİŞ",
    "SONUÇ", "SONUÇLAR", "SONUÇ VE ÖNERİLER", "TARTIŞMA", "BULGULAR", "YÖNTEM",
    "GEREÇ VE YÖNTEM", "MATERYAL VE YÖNTEM", "ETİK BEYAN", "BİLİMSEL ETİK BİLDİRİMİ",
    "INTRODUCTION", "CONCLUSION", "CONCLUSIONS", "ACKNOWLEDGEMENTS", "CONTENTS",
}) | REFERENCE_TITLES | _REFERENCE_END_TITLES
_TOC_LIKE_RE = re.compile(r"(?:\t|\.{4,}|…{2,})\s*[\divxlcIVXLC]{1,5}\s*$")
_REFERENCE_RE = re.compile(
    rf"\[\d{{1,4}}\]\s|\d{{1,4}}\.\s+[{_UPPER}][\w'’\-]+,\s*[{_UPPER}]\.|"
    rf"[{_UPPER}][\w'’\-]+(?:\s[{_UPPER}][\w'’\-]+)?,\s*[{_UPPER}]\.(?:\s?[{_UPPER}]\.)*"
    r"(?:,|\s|\(|&| ve | and )"
)
_YEAR_IN_PARENS_RE = re.compile(r"\((?:19|20)\d{2}[a-z]?\)")
_CITATION_RE = re.compile(
    rf"\([{_UPPER}][^()]{{1,80}}?,?\s(?:19|20)\d{{2}}[a-z]?(?:[,:;][^()]{{0,40}})?\)"
    r"|\[\d{1,4}(?:\s*[,–\-]\s*\d{1,4})*\]"
)


def _normalized_title(text: str) -> str:
    """'1. GİRİŞ' / 'Giriş' / 'BÖLÜM 1: GİRİŞ' → 'GİRİŞ'."""
    t = tr_upper(text.strip())
    t = re.sub(r"^(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s*", "", t)
    t = re.sub(r"^BÖLÜM\s+[\dIVX]+\s*[:.\-–]?\s*", "", t)
    return re.sub(r"\s+", " ", t).strip(" :.")


def number_prefix(text: str) -> NumberPrefix:
    t = text.lstrip()
    if m := _NUM_RE.match(t):
        depth = 1 + m.group(2).count(".")
        return {1: NumberPrefix.ARABIC_1, 2: NumberPrefix.ARABIC_2}.get(
            depth, NumberPrefix.ARABIC_3
        )
    if _ROMAN_RE.match(t):
        return NumberPrefix.ROMAN
    if _LETTER_RE.match(t):
        return NumberPrefix.LETTER
    if _BULLET_RE.match(t):
        return NumberPrefix.BULLET
    return NumberPrefix.NONE


def keyword(text: str) -> Keyword:
    t = text.strip()
    if m := _CAPTION_RE.match(t):
        kw = m.group("kw").replace("İ", "i").casefold()
        return Keyword.TABLE_CAPTION if kw in _TABLE_KW else Keyword.FIGURE_CAPTION
    if len(t) <= 80:
        upper = tr_upper(t)
        if _CHAPTER_RE.match(upper):
            return Keyword.CHAPTER
        title = _normalized_title(t)
        if title in REFERENCE_TITLES:
            return Keyword.REFERENCES_TITLE
        if title in FRONT_TITLES:
            return Keyword.FRONT_TITLE
        if title in SECTION_TITLES:
            return Keyword.SECTION_TITLE
    return Keyword.NONE


def _style_kind(name: str | None, is_default: bool) -> StyleKind:
    if not name or is_default:
        return StyleKind.NONE
    n = name.casefold()
    if m := re.match(r"(?:heading|başlık|baslik)\s*([1-9])", n):
        level = int(m.group(1))
        return {1: StyleKind.HEADING_1, 2: StyleKind.HEADING_2, 3: StyleKind.HEADING_3}.get(
            level, StyleKind.HEADING_OTHER
        )
    if re.match(r"(?:toc|içindekiler|ıçindekiler)\s*\d", n) or n in ("toc heading",):
        return StyleKind.TOC
    table = {
        "title": StyleKind.TITLE, "konu başlığı": StyleKind.TITLE,
        "caption": StyleKind.CAPTION, "resim yazısı": StyleKind.CAPTION,
        "açıklamalı alt yazı": StyleKind.CAPTION,
        "quote": StyleKind.QUOTE, "intense quote": StyleKind.QUOTE, "alıntı": StyleKind.QUOTE,
        "list paragraph": StyleKind.LIST, "liste paragraf": StyleKind.LIST,
        "bibliography": StyleKind.BIBLIOGRAPHY, "kaynakça": StyleKind.BIBLIOGRAPHY,
        "footnote text": StyleKind.FOOTNOTE, "dipnot metni": StyleKind.FOOTNOTE,
        "normal": StyleKind.NONE, "body text": StyleKind.NONE, "gövde metni": StyleKind.NONE,
    }
    return table.get(n, StyleKind.CUSTOM)


def _num_format(fmt: str | None) -> NumFormat:
    if fmt is None:
        return NumFormat.NONE
    if fmt in ("decimal", "decimalZero"):
        return NumFormat.DECIMAL
    if "roman" in fmt.casefold():
        return NumFormat.ROMAN
    if "letter" in fmt.casefold():
        return NumFormat.LETTER
    if fmt == "bullet":
        return NumFormat.BULLET
    if fmt == "none":
        return NumFormat.NONE
    return NumFormat.OTHER


# --- Belge düzeyi bağlam ------------------------------------------------------------------


def page_starts(body: tuple[Paragraph, ...]) -> dict[str, bool]:
    """Paragraf yeni sayfada mı başlıyor: kendi sayfa sonu özelliği, önceki paragraftaki
    elle sayfa sonu ya da bölüm sonu (varsayılan tür: sonraki sayfa)."""
    out: dict[str, bool] = {}
    prev: Paragraph | None = None
    for p in body:
        if p.in_table or p.in_textbox:
            continue
        out[p.para_id] = bool(
            prev is None
            or p.props.page_break_before
            or prev.has_page_break
            or prev.section_index != p.section_index
        )
        prev = p
    return out


def page_tops(body: tuple[Paragraph, ...]) -> dict[str, bool]:
    """Paragraf sayfanın ilk dolu satırı mı: sayfa başıyla arasında yalnızca boş satırlar var
    (sayfa ya da bölüm sonundan sonra boş satır bırakıp başlık yazmak yaygın)."""
    starts = page_starts(body)
    out: dict[str, bool] = {}
    top = False
    for p in body:
        if p.in_table or p.in_textbox:
            continue
        top = top or starts[p.para_id]
        out[p.para_id] = top
        if p.text.strip() or p.has_drawing:
            top = False
    return out


def _body_size(doc: DocModel) -> float | None:
    weights: Counter[float] = Counter()
    for p in doc.body():
        if not p.in_table and not p.in_textbox:
            for run in p.runs:
                if run.props.size_pt:
                    weights[run.props.size_pt] += run.length
    return weights.most_common(1)[0][0] if weights else None


def _looks_like_chapter(p: Paragraph, starts_page: bool) -> bool:
    """Bölüm başlığına benzeyen yapısal işaretler (adı bilinen listede olmasa bile)."""
    name = (p.style_name or "").casefold()
    if re.match(r"(?:heading|başlık|baslik)\s*1(?!\d)", name) or p.props.outline_level == 0:
        return True
    text = p.text.strip()
    if not text or len(text.split()) > 12 or text.endswith((".", "!", "?")):
        return False
    letters = [c for c in text if c.isalpha()]
    caps = bool(letters) and (p.dominant.all_caps or all(c.isupper() for c in letters))
    numbered = number_prefix(text) is NumberPrefix.ARABIC_1
    return (numbered and (bool(p.dominant.bold) or caps)) or (starts_page and caps)


def _front_matter(body: tuple[Paragraph, ...], starts: dict[str, bool]) -> set[str]:
    """Ön sayfa başlığından (ÖNSÖZ, ÖZET...) sonra, ilk ana bölüm başlığına kadarki paragraflar."""
    inside = False
    out: set[str] = set()
    for p in body:
        if p.in_table or p.in_textbox:
            continue
        kw = keyword(p.text)
        if kw is Keyword.FRONT_TITLE:
            inside = True
            continue
        if kw in (Keyword.SECTION_TITLE, Keyword.CHAPTER, Keyword.REFERENCES_TITLE) or (
            inside and _looks_like_chapter(p, starts.get(p.para_id, False))
        ):
            inside = False
            continue
        if inside and p.text.strip():
            out.add(p.para_id)
    return out


def _references_section(body: tuple[Paragraph, ...]) -> set[str]:
    inside = False
    out: set[str] = set()
    for p in body:
        if p.in_table or p.in_textbox:
            continue
        kw = keyword(p.text)
        if kw is Keyword.REFERENCES_TITLE:
            inside = True
            continue
        if inside and (kw in (Keyword.SECTION_TITLE, Keyword.CHAPTER, Keyword.FRONT_TITLE)):
            inside = False
            continue
        if inside and p.text.strip():
            out.add(p.para_id)
    return out


MAX_COVER_PAGES = 5  # dış kapak, iç kapak, onay, beyan ve bir yedek


def _opens_front_matter(p: Paragraph) -> bool:
    """Kapak sayfalarının bittiğini gösteren ilk paragraf: ön sayfa/bölüm başlığı, içindekiler
    alanı ya da 1. düzey başlık stili."""
    if keyword(p.text) in (Keyword.FRONT_TITLE, Keyword.SECTION_TITLE, Keyword.CHAPTER,
                           Keyword.REFERENCES_TITLE) or "TOC" in p.field_kinds:
        return True
    name = (p.style_name or "").casefold()
    return bool(re.match(r"(?:heading|başlık|baslik)\s*1(?!\d)", name)) or (
        p.props.outline_level == 0)


def _cover_pages(body: tuple[Paragraph, ...], starts: dict[str, bool]) -> set[str]:
    """İlk ön sayfa başlığından önceki paragraflar. Böyle bir başlık ilk birkaç sayfada yoksa
    boş küme: kapak yalnızca ilk sayfa sayılır (bkz. _first_page)."""
    out: set[str] = set()
    pages = 1
    for i, p in enumerate(p for p in body if not p.in_table and not p.in_textbox):
        if _opens_front_matter(p):
            return out
        if i > 0 and starts.get(p.para_id, False):
            pages += 1
            if pages > MAX_COVER_PAGES:
                return set()
        out.add(p.para_id)
    return set()


def _first_page(body: tuple[Paragraph, ...], starts: dict[str, bool]) -> set[str]:
    out: set[str] = set()
    for i, p in enumerate(p for p in body if not p.in_table and not p.in_textbox):
        if i > 0 and starts.get(p.para_id, False):
            break
        out.add(p.para_id)
        if p.has_page_break:
            break
    return out


# --- Çıkarım ---------------------------------------------------------------------------------


def extract_features(doc: DocModel) -> dict[str, ParaFeatures]:
    body = doc.body()
    body_pos = {p.para_id: i for i, p in enumerate(body)}
    n_body = max(len(body), 1)
    starts = page_starts(body)
    tops = page_tops(body)
    body_size = _body_size(doc)
    refs = _references_section(body)
    front = _front_matter(body, tops)
    first_page = _first_page(body, starts)
    cover_pages = _cover_pages(body, starts)
    flow = [p for p in body if not p.in_table and not p.in_textbox]
    flow_pos = {p.para_id: i for i, p in enumerate(flow)}

    def neighbour(p: Paragraph, delta: int) -> Paragraph | None:
        i = body_pos.get(p.para_id)
        if i is None:
            return None
        j = i + delta
        return body[j] if 0 <= j < len(body) else None

    out: dict[str, ParaFeatures] = {}
    for p in doc.paragraphs:
        text = p.text
        stripped = text.strip()
        letters = [c for c in stripped if c.isalpha()]
        d = p.dominant
        upper_ratio = (
            1.0 if d.all_caps and letters
            else (sum(c.isupper() for c in letters) / len(letters) if letters else 0.0)
        )
        total = sum(r.length for r in p.runs) or 1
        bold_ratio = sum(r.length for r in p.runs if r.props.bold) / total
        ls = p.props.line_spacing
        next_p = neighbour(p, +1)
        fi = flow_pos.get(p.para_id)
        prev_flow = flow[fi - 1] if fi is not None and fi > 0 else None
        next_flow = flow[fi + 1] if fi is not None and fi + 1 < len(flow) else None

        out[p.para_id] = ParaFeatures(
            story=p.story,
            in_table=p.in_table,
            in_textbox=p.in_textbox,
            section_index=p.section_index,
            relative_position=round(body_pos.get(p.para_id, 0) / n_body, 4),
            starts_page=tops.get(p.para_id, False),
            prev_empty=prev_flow is not None and not prev_flow.text.strip(),
            next_empty=next_flow is not None and not next_flow.text.strip(),
            next_is_table=next_p is not None and next_p.in_table and not p.in_table,
            in_references_section=p.para_id in refs,
            in_front_matter=p.para_id in front,
            on_first_page=p.para_id in first_page,
            on_cover_pages=p.para_id in cover_pages,
            style_kind=_style_kind(p.style_name, is_default=p.style_id is None),
            outline_level=p.props.outline_level,
            size_pt=d.size_pt,
            size_ratio=round(d.size_pt / body_size, 3) if d.size_pt and body_size else None,
            bold=bool(d.bold),
            bold_ratio=round(bold_ratio, 3),
            italic=bool(d.italic),
            all_caps_format=bool(d.all_caps),
            underline=bool(d.underline),
            alignment=p.props.alignment,
            first_line_cm=p.props.first_line_cm,
            indent_left_cm=p.props.indent_left_cm,
            space_before_pt=p.props.space_before_pt,
            space_after_pt=p.props.space_after_pt,
            line_multiple=ls.value if ls and ls.rule is LineRule.AUTO else None,
            keep_next=bool(p.props.keep_next),
            page_break_before=bool(p.props.page_break_before),
            numbering_format=_num_format(p.numbering.num_format if p.numbering else None),
            numbering_level=p.numbering.level if p.numbering else None,
            has_toc_field="TOC" in p.field_kinds,
            has_seq_field="SEQ" in p.field_kinds,
            char_count=len(stripped),
            word_count=len(stripped.split()),
            upper_ratio=round(upper_ratio, 3),
            ends_with_sentence_punct=stripped.endswith((".", "!", "?", "…")),
            ends_with_colon=stripped.endswith(":"),
            number_prefix=number_prefix(stripped),
            keyword=keyword(stripped),
            toc_like=bool(_TOC_LIKE_RE.search(text)),
            reference_like=bool(
                _REFERENCE_RE.match(stripped) or _YEAR_IN_PARENS_RE.search(stripped[:200])
            ) and len(stripped) > 30,
            has_citation=bool(_CITATION_RE.search(stripped)),
        )
    return out
