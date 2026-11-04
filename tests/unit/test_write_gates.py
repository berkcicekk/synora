"""A5 çıktı kapıları: test_fix.py'de sınanmayan üç kapı ve meşru yapı değişikliği."""

from __future__ import annotations

from collections import Counter

import pytest
from thesis import thesis

from synora.errors import ErrorCode
from synora.ingest import open_docx
from synora.write import WriteError, repackage, verify_output

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
BOOKMARK = b'<w:bookmarkStart w:id="99" w:name="eklenen"/><w:bookmarkEnd w:id="99"/>'
NO_FINDINGS: dict[str, object] = {
    "check_findings": lambda _: set(), "before_findings": set(),
    "must_disappear": set(), "allowed_new": set(),
}


def with_bookmark() -> tuple[object, bytes]:
    """Metni değiştirmeden yapıyı değiştirir: metin kapısı bunu göremez."""
    pkg = open_docx(thesis())
    xml = pkg.parts["word/document.xml"].replace(b"<w:body>", b"<w:body>" + BOOKMARK, 1)
    return pkg, repackage(pkg, {"word/document.xml": xml})


def test_gate_rejects_output_that_is_not_a_document() -> None:
    pkg = open_docx(thesis())
    with pytest.raises(WriteError) as exc:
        verify_output(pkg, b"zip degil", modified_parts=set(),  # type: ignore[arg-type]
                      expected_structure_delta=Counter(), **NO_FINDINGS)
    assert exc.value.code is ErrorCode.WRITE_INVALID_OUTPUT


def test_gate_rejects_unexpected_structure_with_same_text() -> None:
    pkg, tampered = with_bookmark()
    with pytest.raises(WriteError) as exc:
        verify_output(pkg, tampered, modified_parts={"word/document.xml"},  # type: ignore[arg-type]
                      expected_structure_delta=Counter(), **NO_FINDINGS)
    assert exc.value.code is ErrorCode.WRITE_STRUCTURE_CHANGED


def test_gate_accepts_structure_change_that_was_declared() -> None:
    pkg, tampered = with_bookmark()
    delta = Counter({f"{W}bookmarkStart": 1, f"{W}bookmarkEnd": 1})
    out = verify_output(pkg, tampered, modified_parts={"word/document.xml"},  # type: ignore[arg-type]
                        expected_structure_delta=delta, **NO_FINDINGS)
    assert out.parts["word/document.xml"].count(b"bookmarkStart") == 1


def test_gate_rejects_output_where_the_fixed_finding_remains() -> None:
    data = thesis()
    pkg = open_docx(data)
    key = ("body.size_pt", "p1", None)
    with pytest.raises(WriteError) as exc:
        verify_output(pkg, data, modified_parts=set(), expected_structure_delta=Counter(),
                      check_findings=lambda _: {key}, before_findings={key},
                      must_disappear={key}, allowed_new=set())
    assert exc.value.code is ErrorCode.WRITE_NOT_RESOLVED
