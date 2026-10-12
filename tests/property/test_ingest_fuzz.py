"""Rastgele ve bozulmuş girdilerde open_docx yalnızca IngestError fırlatabilir."""

import contextlib

from builders import minimal_docx
from hypothesis import given, settings
from hypothesis import strategies as st

from synora.errors import IngestError
from synora.ingest import open_docx

VALID = minimal_docx()


@settings(max_examples=300)
@given(st.binary(max_size=4096))
def test_random_bytes_never_crash(data: bytes) -> None:
    with contextlib.suppress(IngestError):
        open_docx(data)


@settings(max_examples=500)
@given(st.lists(st.tuples(st.integers(0, len(VALID) - 1), st.integers(0, 255)), max_size=8))
def test_mutated_docx_never_crash(mutations: list[tuple[int, int]]) -> None:
    data = bytearray(VALID)
    for pos, value in mutations:
        data[pos] = value
    with contextlib.suppress(IngestError):
        open_docx(bytes(data))
