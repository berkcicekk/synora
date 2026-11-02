"""Ürün adı Sontez: kullanıcının gördüğü hiçbir yerde eski ad (Payper) kalmaz.

Kod adları (`synora` paketi, `SYNORA_*`, `SynoraError`) bilinçli olarak değişmez; bkz.
docs/architecture.md başındaki not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from synora.write import AUTHOR

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SUFFIXES = {".py", ".html", ".js", ".css", ".svg"}
# Depoda olmayan tasarım kaynaklarının klasör adı; ürün adı değil.
ALLOWED = "payper-tasarim"


def source_files() -> list[Path]:
    return [p for p in (ROOT / "src").rglob("*")
            if p.suffix in SOURCE_SUFFIXES and "__pycache__" not in p.parts]


def test_scan_covers_the_frontend() -> None:
    names = {p.name for p in source_files()}
    assert {"base.html", "app.js", "app.css", "app.py", "write.py", "logo.svg"} <= names


@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
def test_old_product_name_is_gone(path: Path) -> None:
    text = path.read_text(encoding="utf-8").lower().replace(ALLOWED, "")
    assert "payper" not in text


def test_tracked_changes_author_is_sontez() -> None:
    assert AUTHOR == "Sontez"


def test_visible_markup_does_not_use_old_code_name() -> None:
    assert 'aria-label="Synora"' not in (ROOT / "src/synora/web/static/logo.svg").read_text("utf-8")
