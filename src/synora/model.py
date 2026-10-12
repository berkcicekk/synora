"""DocModel: denetim motorunun gördüğü belge.

Biçim değerleri stil kalıtımı çözülmüş halde ve insan birimlerinde (cm, pt) tutulur.
Paragraf metni bellekte durur ama repr'den hariçtir; hata çıktısına ya da log'a sızmaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from enum import StrEnum
from typing import Self


class Story(StrEnum):
    BODY = "body"
    FOOTNOTE = "footnote"
    ENDNOTE = "endnote"
    HEADER = "header"
    FOOTER = "footer"


class Role(StrEnum):
    TITLE = "title"
    HEADING_1 = "heading_1"
    HEADING_2 = "heading_2"
    HEADING_3 = "heading_3"
    BODY = "body"
    BLOCK_QUOTE = "block_quote"
    LIST_ITEM = "list_item"
    FIGURE_CAPTION = "figure_caption"
    TABLE_CAPTION = "table_caption"
    REFERENCE_ENTRY = "reference_entry"
    TOC_ENTRY = "toc_entry"
    FOOTNOTE = "footnote"
    ENDNOTE = "endnote"
    TABLE_CELL = "table_cell"
    TEXTBOX = "textbox"
    HEADER_FOOTER = "header_footer"
    COVER = "cover"  # kapak sayfası satırları
    FRONT_MATTER = "front_matter"  # önsöz, özet, dizinler gibi ön sayfaların metni
    EMPTY = "empty"
    UNKNOWN = "unknown"


class Alignment(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class LineRule(StrEnum):
    AUTO = "auto"  # value = satır katsayısı (1.0, 1.5, 2.0)
    EXACT = "exact"  # value = pt
    AT_LEAST = "at_least"  # value = pt


class _Mergeable:
    """None alanlar 'tanımsız' demektir; merge sonraki katmanın tanımlı değerlerini yazar."""

    __slots__ = ()

    def merge(self, other: Self) -> Self:
        updates = {
            f.name: getattr(other, f.name)
            for f in fields(other)  # type: ignore[arg-type]
            if getattr(other, f.name) is not None
        }
        return replace(self, **updates)  # type: ignore[type-var]


@dataclass(frozen=True, slots=True)
class LineSpacing:
    rule: LineRule
    value: float


@dataclass(frozen=True, slots=True)
class NumberingRef:
    num_id: int
    level: int
    num_format: str | None = None  # decimal, upperRoman, lowerLetter, bullet...
    level_text: str | None = None  # "%1.%2." gibi desen


@dataclass(frozen=True, slots=True)
class ParaProps(_Mergeable):
    alignment: Alignment | None = None
    indent_left_cm: float | None = None
    indent_right_cm: float | None = None
    first_line_cm: float | None = None  # asılı girinti negatif
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    line_spacing: LineSpacing | None = None
    keep_next: bool | None = None
    page_break_before: bool | None = None
    outline_level: int | None = None
    num_id: int | None = None
    num_level: int | None = None


@dataclass(frozen=True, slots=True)
class RunProps(_Mergeable):
    font: str | None = None
    size_pt: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    all_caps: bool | None = None
    small_caps: bool | None = None
    vert_align: str | None = None  # superscript / subscript


@dataclass(frozen=True, slots=True)
class RunInfo:
    """Bir run'ın çözülmüş biçimi ve uzunluğu. Metnin kendisi burada tutulmaz."""

    props: RunProps
    length: int
    field_kind: str | None = None  # içinde bulunduğu alanın türü: PAGE, SEQ, TOC, ADDIN...
    inserted: bool = False  # değişiklik izleme: eklenmiş


@dataclass(frozen=True, slots=True)
class Margins:
    top_cm: float | None
    bottom_cm: float | None
    left_cm: float | None
    right_cm: float | None
    header_cm: float | None
    footer_cm: float | None
    gutter_cm: float | None


@dataclass(frozen=True, slots=True)
class Section:
    index: int
    page_width_cm: float | None
    page_height_cm: float | None
    landscape: bool
    margins: Margins
    page_number_format: str | None  # decimal, lowerRoman...
    page_number_start: int | None
    title_page: bool
    headers: dict[str, str] = field(default_factory=dict)  # tür (default/first/even) → part
    footers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Paragraph:
    para_id: str
    story: Story
    part: str
    index: int  # part içindeki sıra
    section_index: int | None  # yalnızca BODY
    style_id: str | None
    style_name: str | None
    props: ParaProps  # çözülmüş
    numbering: NumberingRef | None
    runs: tuple[RunInfo, ...]
    dominant: RunProps  # karakter sayısına göre baskın run biçimi
    in_table: bool
    in_textbox: bool
    has_page_break: bool  # paragraf içinde elle sayfa sonu
    has_drawing: bool  # paragraf bir resim/çizim/nesne taşıyor (şekil)
    field_kinds: frozenset[str]
    text: str = field(repr=False)

    @property
    def char_count(self) -> int:
        return sum(r.length for r in self.runs)


@dataclass(frozen=True, slots=True)
class DocModel:
    sections: tuple[Section, ...]
    paragraphs: tuple[Paragraph, ...]
    has_tracked_changes: bool
    source_sha256: str

    def body(self) -> tuple[Paragraph, ...]:
        return tuple(p for p in self.paragraphs if p.story is Story.BODY)
