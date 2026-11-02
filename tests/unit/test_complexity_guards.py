"""Küçük dosya işçiyi tutamaz: regex ve alan yürüyüşü doğrusal; bozuk değerler işi düşürmez."""

from __future__ import annotations

import time

import pytest
from lxml import etree

from synora.check import listed_in_toc, strip_toc_tail
from synora.features import Keyword, is_toc_like, keyword
from synora.ooxml import measure_twips, to_int
from synora.text import FieldTracker, iter_runs, sym_char
from synora.write import RevisionIds

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
LONG = 1_000_000
LIMIT_SECONDS = 1.0


def fast(func, *args):  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    result = func(*args)
    assert time.perf_counter() - started < LIMIT_SECONDS
    return result


# --- Regex ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "." * LONG + "!",
    "\t" * LONG + "a",
    " " * LONG + "a",
    "…" * LONG + "a",
    "." * LONG + " " * LONG + "x",
], ids=["nokta", "sekme", "bosluk", "uc-nokta", "nokta-bosluk"])
def test_toc_detection_is_linear(text: str) -> None:
    assert fast(is_toc_like, text) is False


@pytest.mark.parametrize(("text", "expected"), [
    ("GİRİŞ ........ 12", True),
    ("GİRİŞ\t12", True),
    ("Özet …… iv", True),
    ("GİRİŞ ........ 12" + " " * 500, True),
    ("Bu bir gövde cümlesidir.", False),
    ("Yılı 2012", False),
])
def test_toc_detection_still_works(text: str, expected: bool) -> None:
    assert is_toc_like(text) is expected


@pytest.mark.parametrize("text", [
    "Şekil 1" + " " * LONG + "a",
    "Tablo 1" + "\t" * LONG + "a",
    "Şekil 1." + " " * LONG,
], ids=["bosluk", "sekme", "nokta-bosluk"])
def test_caption_keyword_is_linear(text: str) -> None:
    fast(keyword, text)


@pytest.mark.parametrize(("text", "expected"), [
    ("Şekil 3.1. Hasta dağılımı", Keyword.FIGURE_CAPTION),
    ("Tablo 2: Sonuçlar", Keyword.TABLE_CAPTION),
])
def test_caption_keyword_still_works(text: str, expected: Keyword) -> None:
    assert keyword(text) is expected


@pytest.mark.parametrize("text", [" ." * LONG + "x", " " * LONG + "x", " " * LONG + "12x"],
                         ids=["bosluk-nokta", "bosluk", "bosluk-sayi"])
def test_toc_tail_strip_is_linear(text: str) -> None:
    fast(strip_toc_tail, text)


@pytest.mark.parametrize(("text", "expected"), [
    ("GİRİŞ ........ 12", "GİRİŞ"),
    ("GİRİŞ\t12", "GİRİŞ"),
    ("GİRİŞ 12", "GİRİŞ"),
    ("GİRİŞ", "GİRİŞ"),
])
def test_toc_tail_strip_still_works(text: str, expected: str) -> None:
    assert strip_toc_tail(text) == expected


# --- İçindekiler karşılaştırması ------------------------------------------------------------------


def test_listed_in_toc_matches_previous_definition() -> None:
    entries = ["giriş", "ab", "yöntem ve gereçler", "x" * 80, "bulgular ve tartışma"]
    heads = ["giriş", "giriş ve amaç", "yöntem", "ab", "abc", "x" * 60, "sonuç", "bulgular"]

    def old(head: str) -> bool:
        return any(e.startswith(head[:50]) or (len(e) >= 3 and head.startswith(e[:50]))
                   for e in entries)

    listed = listed_in_toc(entries)
    assert [listed(h) for h in heads] == [old(h) for h in heads]


def test_listed_in_toc_scales() -> None:
    entries = [f"bölüm {i} başlığı" for i in range(5000)]
    listed = listed_in_toc(entries)
    started = time.perf_counter()
    assert not any(listed(f"yok {i} başlığı") for i in range(5000))
    assert time.perf_counter() - started < LIMIT_SECONDS


# --- Alan yürüyüşü --------------------------------------------------------------------------------


def run(xml: str) -> etree._Element:
    return etree.fromstring(f'<w:p xmlns:w="{W}">{xml}</w:p>')


def texts(xml: str, tracker: FieldTracker | None = None) -> list[tuple[str, str | None]]:
    walked = iter_runs(run(xml), tracker or FieldTracker())
    return [(r.text, r.field_kind) for r in walked]


def fld(kind: str) -> str:
    return f'<w:r><w:fldChar w:fldCharType="{kind}"/></w:r>'


def test_field_kind_and_instruction_are_tracked() -> None:
    xml = (fld("begin") + "<w:r><w:instrText> TOC \\o </w:instrText></w:r>" + fld("separate")
           + "<w:r><w:t>sonuç</w:t></w:r>" + fld("end") + "<w:r><w:t>sonra</w:t></w:r>")
    assert [t for t in texts(xml) if t[0]] == [("sonuç", "TOC"), ("sonra", None)]


def test_text_inside_instruction_is_not_visible() -> None:
    xml = (fld("begin") + "<w:r><w:t>gizli</w:t></w:r>" + fld("separate")
           + "<w:r><w:t>gorunur</w:t></w:r>")
    assert [t[0] for t in texts(xml) if t[0]] == ["gorunur"]


def test_nested_fields_restore_outer_kind() -> None:
    xml = (fld("begin") + "<w:r><w:instrText>TOC</w:instrText></w:r>" + fld("separate")
           + fld("begin") + "<w:r><w:instrText>PAGEREF x</w:instrText></w:r>" + fld("separate")
           + "<w:r><w:t>ic</w:t></w:r>" + fld("end") + "<w:r><w:t>dis</w:t></w:r>" + fld("end"))
    assert [t for t in texts(xml) if t[0]] == [("ic", "PAGEREF"), ("dis", "TOC")]


def test_unmatched_field_chars_do_not_crash() -> None:
    tracker = FieldTracker()
    tracker.end()
    tracker.separate()
    tracker.instr("X")
    assert tracker.kind is None and not tracker.in_instruction


def test_double_separate_counts_once() -> None:
    tracker = FieldTracker()
    tracker.begin()
    tracker.separate()
    tracker.separate()
    assert not tracker.in_instruction
    tracker.end()
    assert not tracker.in_instruction


def test_tracker_scales_with_long_instruction_and_many_fields() -> None:
    tracker = FieldTracker()
    started = time.perf_counter()
    tracker.begin()
    for _ in range(4000):
        tracker.instr("x" * 200)
    tracker.separate()
    for _ in range(20000):
        tracker.begin()
        tracker.separate()
    for _ in range(100000):
        assert tracker.kind == "UNKNOWN"
        assert not tracker.in_instruction
    assert time.perf_counter() - started < LIMIT_SECONDS


# --- Bozuk değerler -------------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["D800", "DFFF"])
def test_surrogate_symbol_becomes_replacement_char(code: str) -> None:
    assert sym_char(code) == "�"
    assert sym_char(code).encode()


@pytest.mark.parametrize(("code", "expected"), [
    ("F0B7", ""), ("41", "A"), ("", ""), (None, ""), ("zz", "�"), ("FFFFFFFF", "�"),
])
def test_symbol_codes(code: str | None, expected: str) -> None:
    assert sym_char(code) == expected


@pytest.mark.parametrize("value", ["1" + "0" * 400, "9" * 5000, "²", "abc", ""],
                         ids=["400-hane", "5000-hane", "ust-simge", "harf", "bos"])
def test_to_int_rejects_absurd_values(value: str) -> None:
    assert to_int(value) is None


@pytest.mark.parametrize(("value", "expected"), [("12", 12), ("-5", -5), ("+7", 7), (" 8 ", 8)])
def test_to_int_accepts_integers(value: str, expected: int) -> None:
    assert to_int(value) == expected


@pytest.mark.parametrize("value", ["1" + "0" * 400 + "cm", "1" + "0" * 400, "٣cm"],
                         ids=["400-hane-cm", "400-hane", "arap-rakam"])
def test_measure_rejects_absurd_values(value: str) -> None:
    assert measure_twips(value) is None


def test_measure_accepts_universal_units() -> None:
    assert measure_twips("1in") == 1440.0
    assert measure_twips("720") == 720.0


def test_revision_ids_ignore_malformed_values() -> None:
    root = etree.fromstring(
        f'<a xmlns:w="{W}"><w:b w:id="²"/><w:b w:id="{"9" * 5000}"/><w:b w:id="41"/></a>')
    assert RevisionIds.for_roots([root]).next_id == 42
