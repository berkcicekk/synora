"""Mimari kurallar: güvensiz XML kütüphaneleri kaynakta kullanılamaz."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "synora"
BANNED = ("xml.etree", "xml.dom", "xml.sax", "xml.parsers.expat", "docx")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_no_banned_xml_imports() -> None:
    offenders = [
        f"{p.relative_to(SRC)}: {name}"
        for p in SRC.rglob("*.py")
        for name in _imports(p)
        if any(name == b or name.startswith(b + ".") for b in BANNED)
    ]
    assert offenders == []


def test_lxml_etree_only_in_xmlsafe() -> None:
    offenders = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if p.name != "xmlsafe.py"
        and any(n == "lxml" or n.startswith("lxml.") for n in _imports(p))
        and "fromstring" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
