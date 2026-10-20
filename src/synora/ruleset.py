"""A3 — Kural seti: enstitü yazım kılavuzunun makine tarafından okunabilir hali.

YAML yalnızca safe_load ile okunur; şemada olmayan her alan hatadır (extra="forbid").
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from synora.model import Alignment, Role


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PageNumberFormat(StrEnum):
    ARABIC = "decimal"
    LOWER_ROMAN = "lowerRoman"
    UPPER_ROMAN = "upperRoman"


PAGE_SIZES_CM: dict[str, tuple[float, float]] = {
    "A4": (21.0, 29.7),
    "A5": (14.8, 21.0),
    "B5": (17.6, 25.0),
    "Letter": (21.59, 27.94),
}


class Tolerance(_Strict):
    length_cm: float = Field(0.05, ge=0)
    size_pt: float = Field(0.25, ge=0)
    spacing_pt: float = Field(0.5, ge=0)
    line_multiple: float = Field(0.05, ge=0)


class Margins(_Strict):
    top: float | None = Field(None, ge=0)
    bottom: float | None = Field(None, ge=0)
    left: float | None = Field(None, ge=0)
    right: float | None = Field(None, ge=0)


class PageRules(_Strict):
    size: Literal["A4", "A5", "B5", "Letter"] | None = None
    orientation: Literal["portrait", "landscape"] | None = None
    margins_cm: Margins | None = None


class FontRules(_Strict):
    allowed: tuple[str, ...] = ()


class LineSpacingRule(_Strict):
    multiple: float | None = Field(None, gt=0)
    exact_pt: float | None = Field(None, gt=0)
    at_least_pt: float | None = Field(None, gt=0)

    @model_validator(mode="after")
    def _exactly_one(self) -> LineSpacingRule:
        if sum(v is not None for v in (self.multiple, self.exact_pt, self.at_least_pt)) != 1:
            raise ValueError("line_spacing: multiple, exact_pt, at_least_pt'den tam biri verilmeli")
        return self


class RoleRules(_Strict):
    font: tuple[str, ...] | None = None  # verilmezse fonts.allowed
    size_pt: float | None = Field(None, gt=0)
    bold: bool | None = None
    italic: bool | None = None
    all_caps: bool | None = None
    alignment: Alignment | None = None
    line_spacing: LineSpacingRule | float | None = None  # düz sayı = katsayı
    first_line_indent_cm: float | None = None
    indent_left_cm: float | None = None
    space_before_pt: float | None = Field(None, ge=0)
    space_after_pt: float | None = Field(None, ge=0)
    page_break_before: bool | None = None
    # Şekil/tablo başlığının nesneye göre yeri
    position: Literal["above", "below"] | None = None
    # Başlık yazımı: title = Her Sözcüğün İlk Harfi Büyük (bağlaçlar küçük);
    # sentence = yalnızca ilk sözcüğün ilk harfi büyük
    case: Literal["title", "sentence"] | None = None

    def spacing_rule(self) -> LineSpacingRule | None:
        if isinstance(self.line_spacing, float | int):
            return LineSpacingRule(multiple=float(self.line_spacing))
        return self.line_spacing


PageNumberPosition = Literal["bottom_left", "bottom_center", "bottom_right",
                             "top_left", "top_center", "top_right"]


class PageNumbering(_Strict):
    # Bölümlerin sayfa numarası biçimleri, sırayla (art arda tekrarlar tek sayılır).
    formats_in_order: tuple[PageNumberFormat, ...] = ()
    position: PageNumberPosition | None = None
    # Sayfa numarasının yanında parantez, tire vb. olmamalı
    forbid_decoration: bool = False


class DocumentRules(_Strict):
    forbid_tracked_changes: bool = True


class Ruleset(_Strict):
    ruleset: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    version: int = Field(ge=1)
    name: str
    source: str | None = None  # kılavuzun adı/tarihi
    institution: str | None = None  # üniversite adı; arayüzde seçenekler buna göre gruplanır
    source_url: str | None = Field(None, pattern=r"^https?://[^\s]+$")  # kılavuzun resmi adresi
    # Kullanıcıya gösterilecek uyarı: ör. enstitünün güncel şablonu bu kılavuzla çelişiyor.
    uyari: str | None = None
    tolerance: Tolerance = Tolerance()
    page: PageRules = PageRules()
    fonts: FontRules = FontRules()
    roles: dict[Role, RoleRules] = {}
    page_numbering: PageNumbering = PageNumbering()
    document: DocumentRules = DocumentRules()


def load_ruleset(path: str | Path) -> Ruleset:
    # SafeLoader'ın C sürümü (varsa): aynı güvenli alt küme, 200+ kural setinde belirgin hızlı.
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    with open(path, encoding="utf-8") as fh:
        data = yaml.load(fh, Loader=loader)  # noqa: S506 — yalnızca SafeLoader/CSafeLoader
    return Ruleset.model_validate(data)
