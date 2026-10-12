"""ParaFeatures gizlilik sözleşmesi ve desen çıkarıcıları."""

import types
import typing
from enum import Enum

import pytest
from builders import make_docx, p, r

from synora.features import (
    Keyword,
    NumberPrefix,
    ParaFeatures,
    extract_features,
    keyword,
    number_prefix,
)
from synora.ingest import open_docx
from synora.parse import parse_package

SECRET = "Gizli tez cümlesi Yılmaz (2020) tarafından önerilen yöntemle"


def _leaf_types(tp: object) -> list[object]:
    args = typing.get_args(tp)
    if not args:
        return [tp]
    out: list[object] = []
    for a in args:
        out.extend(_leaf_types(a))
    return out


def test_no_plain_str_fields() -> None:
    """Sınıflandırıcıya (ve ileride bir LLM'e) metin sızamaz: düz str tipli alan yasak."""
    offenders = []
    for name, field in ParaFeatures.model_fields.items():
        for leaf in _leaf_types(field.annotation):
            if leaf is type(None):
                continue
            if isinstance(leaf, type) and issubclass(leaf, Enum):
                continue
            if leaf in (bool, int, float):
                continue
            offenders.append((name, leaf))
    assert offenders == []


def test_features_reject_extra_fields() -> None:
    with pytest.raises(Exception, match="extra"):
        ParaFeatures.model_validate({"text": "x"})


def test_serialized_features_contain_no_text() -> None:
    doc = parse_package(open_docx(make_docx(p(SECRET) + p(r("1.1 Amaç", rpr="<w:b/>")))))
    feats = extract_features(doc)
    dumped = " ".join(f.model_dump_json() for f in feats.values())
    for word in SECRET.split():
        if len(word) > 3:
            assert word not in dumped
    assert "Amaç" not in dumped


def test_union_types_are_inspected() -> None:
    assert type(None) in _leaf_types(int | None)
    assert isinstance(int | None, types.UnionType)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1. GİRİŞ", NumberPrefix.ARABIC_1),
        ("1 GİRİŞ", NumberPrefix.ARABIC_1),
        ("2.3 Yöntem", NumberPrefix.ARABIC_2),
        ("2.3. Yöntem", NumberPrefix.ARABIC_2),
        ("2.3.1. Veri", NumberPrefix.ARABIC_3),
        ("IV. Sonuç", NumberPrefix.ROMAN),
        ("a) birinci madde", NumberPrefix.LETTER),
        ("• madde", NumberPrefix.BULLET),
        ("2020 yılında yapılan", NumberPrefix.NONE),
        ("Giriş", NumberPrefix.NONE),
    ],
)
def test_number_prefix(text: str, expected: NumberPrefix) -> None:
    assert number_prefix(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Şekil 3.1. Araştırma modeli", Keyword.FIGURE_CAPTION),
        ("Şekil 3.1 Araştırma modeli", Keyword.FIGURE_CAPTION),
        ("Şekil 3: Araştırma modeli", Keyword.FIGURE_CAPTION),
        ("Tablo 2.4. Katılımcıların dağılımı", Keyword.TABLE_CAPTION),
        ("Çizelge 1.2 Ölçüm sonuçları", Keyword.TABLE_CAPTION),
        ("Table 4 Results", Keyword.TABLE_CAPTION),
        ("ŞEKİL 1.1 Model", Keyword.FIGURE_CAPTION),
        ("ÇİZELGE 2.3 Bulgular", Keyword.TABLE_CAPTION),
        ("TABLO 2.3 Bulgular", Keyword.TABLE_CAPTION),
        # Gövde cümleleri başlık sayılmamalı
        ("Şekil 3'te görüldüğü gibi model iki aşamalıdır.", Keyword.NONE),
        ("Şekil 3.1 ve Şekil 3.2 karşılaştırıldığında fark açıktır.", Keyword.NONE),
        ("Tablo 2.1’de katılımcı sayıları verilmiştir.", Keyword.NONE),
        ("GİRİŞ", Keyword.SECTION_TITLE),
        ("1. GİRİŞ", Keyword.SECTION_TITLE),
        ("Giriş", Keyword.SECTION_TITLE),
        ("İÇİNDEKİLER", Keyword.SECTION_TITLE),
        ("KAYNAKLAR", Keyword.REFERENCES_TITLE),
        ("Kaynakça", Keyword.REFERENCES_TITLE),
        ("BİRİNCİ BÖLÜM", Keyword.CHAPTER),
        ("BÖLÜM 2", Keyword.CHAPTER),
        ("Girişimcilik eğitimi üzerine bir inceleme", Keyword.NONE),
    ],
)
def test_keyword(text: str, expected: Keyword) -> None:
    assert keyword(text) == expected
