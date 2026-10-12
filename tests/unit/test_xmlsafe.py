import pytest

from synora.errors import ErrorCode, UnsafeXmlError
from synora.xmlsafe import parse

SECRET = "GIZLI-TEZ-CUMLESI"


def test_parses_plain_xml() -> None:
    root = parse(b'<?xml version="1.0"?><a xmlns="urn:x"><b>1</b></a>')
    assert root.tag == "{urn:x}a"


def test_rejects_internal_doctype() -> None:
    with pytest.raises(UnsafeXmlError) as exc:
        parse(b'<!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>')
    assert exc.value.code is ErrorCode.XML_DOCTYPE


def test_rejects_external_entity_xxe() -> None:
    xml = b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'
    with pytest.raises(UnsafeXmlError) as exc:
        parse(xml)
    assert exc.value.code is ErrorCode.XML_DOCTYPE


def test_rejects_billion_laughs() -> None:
    ents = '<!ENTITY a0 "lol">' + "".join(
        f'<!ENTITY a{i} "{("&a" + str(i - 1) + ";") * 10}">' for i in range(1, 10)
    )
    xml = f"<!DOCTYPE r [{ents}]><r>&a9;</r>".encode()
    with pytest.raises(UnsafeXmlError) as exc:
        parse(xml)
    assert exc.value.code is ErrorCode.XML_DOCTYPE


def test_rejects_doctype_in_utf16() -> None:
    xml = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>'
    with pytest.raises(UnsafeXmlError) as exc:
        parse(xml.encode("utf-16"))
    assert exc.value.code is ErrorCode.XML_DOCTYPE


def test_rejects_external_dtd_reference() -> None:
    with pytest.raises(UnsafeXmlError) as exc:
        parse(b'<!DOCTYPE a SYSTEM "http://example.invalid/a.dtd"><a/>')
    assert exc.value.code is ErrorCode.XML_DOCTYPE


def test_rejects_oversized_input() -> None:
    with pytest.raises(UnsafeXmlError) as exc:
        parse(b"<a>" + b"x" * 100 + b"</a>", max_bytes=50)
    assert exc.value.code is ErrorCode.XML_TOO_LARGE


def test_malformed_xml_error_does_not_leak_content() -> None:
    with pytest.raises(UnsafeXmlError) as exc:
        parse(f"<a><b>{SECRET}</a>".encode())
    err = exc.value
    assert err.code is ErrorCode.XML_MALFORMED
    assert SECRET not in str(err)
    assert SECRET not in repr(err)
    assert err.__cause__ is None
    assert err.__suppress_context__
