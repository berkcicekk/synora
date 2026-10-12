import pytest
from builders import HYPERLINK_REL, minimal_parts, zip_parts

from synora.errors import ErrorCode, IngestError
from synora.ingest import _check_part_name, open_docx


@pytest.mark.parametrize("name", ["word\\doc.xml", "a\x00b.xml", "a\nb.xml", "", "x/../y"])
def test_check_part_name_rejects(name: str) -> None:
    with pytest.raises(IngestError) as exc:
        _check_part_name(name)
    assert exc.value.code is ErrorCode.BAD_PART_NAME


@pytest.mark.parametrize("name", ["[Content_Types].xml", "_rels/.rels", "word/media/"])
def test_check_part_name_accepts(name: str) -> None:
    _check_part_name(name)


def test_opens_valid_docx(valid_docx: bytes) -> None:
    pkg = open_docx(valid_docx)
    assert pkg.main_part == "word/document.xml"
    assert set(pkg.parts) == {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
    assert pkg.parts["word/document.xml"].startswith(b"<?xml")
    assert len(pkg.sha256) == 64


def test_parts_are_read_only(valid_docx: bytes) -> None:
    pkg = open_docx(valid_docx)
    try:
        pkg.parts["word/document.xml"] = b""  # type: ignore[index]
    except TypeError:
        pass
    else:
        raise AssertionError("parts değiştirilebilir olmamalı")


def test_external_relationships_recorded_not_followed() -> None:
    parts = minimal_parts()
    parts["word/_rels/document.xml.rels"] = (
        '<?xml version="1.0"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId9" Type="{HYPERLINK_REL}" '
        'Target="http://ornek.invalid/gizli-yol" TargetMode="External"/>'
        "</Relationships>"
    ).encode()
    pkg = open_docx(zip_parts(parts))
    assert len(pkg.external_relationships) == 1
    ext = pkg.external_relationships[0]
    assert ext.rels_part == "word/_rels/document.xml.rels"
    assert ext.rel_id == "rId9"
    assert ext.rel_type == HYPERLINK_REL
    # Hedef URL belge içeriğidir; pakette tutulmaz.
    assert "gizli-yol" not in repr(ext)


def test_directory_entries_are_ignored() -> None:
    parts = [*list(minimal_parts().items()), ("word/media/", b"")]
    pkg = open_docx(zip_parts(parts))
    assert "word/media/" not in pkg.parts
