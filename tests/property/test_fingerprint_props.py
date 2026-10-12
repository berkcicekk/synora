"""Fingerprint değişmezlikleri.

Biçim ve run bölünmesi özeti etkilemez; metin değişikliği etkiler.
"""

from builders import make_docx, p, r
from hypothesis import given, settings
from hypothesis import strategies as st

from synora.fingerprint import content_fingerprint
from synora.ingest import open_docx

ALPHABET = st.characters(
    codec="utf-8",
    categories=("L", "N", "P", "Zs"),
    include_characters="çğıİöşüÇĞÖŞÜ",
)
TEXTS = st.lists(st.text(ALPHABET, max_size=40), min_size=1, max_size=6)
RPR = st.sampled_from(
    ["", "<w:b/>", "<w:i/>", '<w:sz w:val="28"/>', '<w:rFonts w:ascii="Arial"/>', "<w:caps/>"]
)
PPR = st.sampled_from(
    ["", '<w:jc w:val="center"/>', '<w:spacing w:line="360"/>', '<w:ind w:firstLine="709"/>']
)


def fingerprint(body: str) -> str:
    return content_fingerprint(open_docx(make_docx(body)))


@st.composite
def rendering(draw: st.DrawFn, texts: list[str]) -> str:
    """Aynı metinleri rastgele biçim ve rastgele run bölünmesiyle yazar."""
    paras = []
    for text in texts:
        cuts = sorted(draw(st.lists(st.integers(0, len(text)), max_size=4)))
        pieces = [text[a:b] for a, b in zip([0, *cuts], [*cuts, len(text)], strict=True)]
        runs = [r(piece, rpr=draw(RPR)) for piece in pieces if piece]
        paras.append(p(*runs, ppr=draw(PPR)))
    return "".join(paras)


@settings(max_examples=150, deadline=None)
@given(st.data(), TEXTS)
def test_formatting_and_run_splits_never_change_fingerprint(data: st.DataObject,
                                                             texts: list[str]) -> None:
    a = data.draw(rendering(texts))
    b = data.draw(rendering(texts))
    assert fingerprint(a) == fingerprint(b)


@settings(max_examples=150, deadline=None)
@given(st.data(), TEXTS)
def test_any_text_change_changes_fingerprint(data: st.DataObject, texts: list[str]) -> None:
    i = data.draw(st.integers(0, len(texts) - 1))
    original = texts[i]
    pos = data.draw(st.integers(0, len(original)))
    new_char = data.draw(ALPHABET)
    mode = data.draw(st.sampled_from(["insert", "replace", "delete"]))
    if mode == "insert":
        changed = original[:pos] + new_char + original[pos:]
    elif mode == "replace" and pos < len(original) and original[pos] != new_char:
        changed = original[:pos] + new_char + original[pos + 1 :]
    elif mode == "delete" and pos < len(original):
        changed = original[:pos] + original[pos + 1 :]
    else:
        changed = original + new_char
    mutated = [*texts[:i], changed, *texts[i + 1 :]]
    assert fingerprint(data.draw(rendering(texts))) != fingerprint(data.draw(rendering(mutated)))
