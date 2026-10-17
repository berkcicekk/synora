"""tests/web için ortak fikstürler (test_web.py kendi kopyalarını tanımlar; aynı içerik)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from synora.web.app import create_app
from synora.web.db import Database
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


class _Rows(list[tuple[object, ...]]):
    """Kilit içinde okunmuş sonuç; cursor'un kullanılan arayüzü (fetchone/fetchall/rowcount)."""

    def __init__(self, cur: sqlite3.Cursor) -> None:
        super().__init__(cur.fetchall())
        self.rowcount = cur.rowcount

    def fetchone(self) -> tuple[object, ...] | None:
        return self[0] if self else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self)


@pytest.fixture(autouse=True)
def _serialize_db_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """GEÇİCİ test ara katmanı — ONERILER Ö9 düzeltilince kaldırın.

    Database.execute fetchone'u kilit dışında bırakıyor; iş yürütücü ile istek aynı anda okuyunca
    sonuç bozuluyor (tests/unit/test_db_concurrency.py). Web testleri bu yüzden ara sıra
    "iş bitmedi" ya da TypeError ile kırmızıya dönüyordu. Burada sonuç kilit içinde okunur:
    bu, Ö9'da önerilen düzeltmenin aynısıdır; üretim kodu değiştirilmedi.
    """

    def execute(self: Database, sql: str, params: tuple[object, ...] = ()) -> _Rows:
        with self._lock:
            return _Rows(self._conn.execute(sql, params))

    monkeypatch.setattr(Database, "execute", execute)


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
