"""tests/web için ortak fikstürler (test_web.py kendi kopyalarını tanımlar; aynı içerik)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from synora.web.app import create_app
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def mailer() -> ConsoleMailer:
    return ConsoleMailer(echo=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "t.db", rulesets_dir=ROOT / "rulesets", base_url="http://testserver",
        allowed_domains=("beun.edu.tr",), dev=True, isolate_jobs=False, workers=1,
    )


@pytest.fixture
def client(settings: Settings, mailer: ConsoleMailer) -> Iterator[TestClient]:
    with TestClient(create_app(settings, mailer)) as c:
        yield c
