"""İşletim: gerçek sağlık denetimi, bozuk kılavuz dosyası açılışı çökertmez, statik önbellek."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from synora.web.app import create_app, discover_rulesets
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_health_reports_ok_when_db_and_workers_run(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200 and res.json() == {"status": "ok"}


def test_health_fails_when_a_worker_thread_died(client: TestClient) -> None:
    runner = client.app.state.runner  # type: ignore[attr-defined]
    runner.alive = lambda: False
    res = client.get("/health")
    assert res.status_code == 503 and res.json()["status"] == "degraded"


def test_health_fails_when_database_is_unusable(client: TestClient) -> None:
    db = client.app.state.db  # type: ignore[attr-defined]

    def broken(*args: object) -> None:
        raise OSError("disk")

    db.execute = broken
    assert client.get("/health").status_code == 503


def test_broken_yaml_is_skipped(tmp_path: Path, settings: Settings,
                                mailer: ConsoleMailer) -> None:
    shutil.copy(ROOT / "rulesets" / "example.yaml", tmp_path / "example.yaml")
    shutil.copy(ROOT / "rulesets" / "zbeu-tip.yaml", tmp_path / "zbeu-tip.yaml")
    (tmp_path / "bozuk.yaml").write_text("ruleset: [kapanmayan\n  : :", encoding="utf-8")
    assert set(discover_rulesets(tmp_path)) == {"example", "zbeu-tip"}
    with TestClient(create_app(replace(settings, rulesets_dir=tmp_path), mailer)) as c:
        assert c.get("/health").status_code == 200


def test_versioned_static_files_are_cached_long(client: TestClient) -> None:
    page = client.get("/").text
    css = page.split('href="/static/app.css?v=')[1].split('"')[0]
    res = client.get(f"/static/app.css?v={css}")
    assert "immutable" in res.headers["cache-control"]
    assert "immutable" not in client.get("/static/app.css").headers.get("cache-control", "")


def test_robots_and_security_txt(client: TestClient) -> None:
    # Güvenlik filtrelerinin (ör. Cisco Umbrella) baktığı meşruiyet sinyalleri.
    robots = client.get("/robots.txt")
    assert robots.status_code == 200 and "User-agent" in robots.text
    sec = client.get("/.well-known/security.txt")
    assert sec.status_code == 200
    assert "Contact:" in sec.text and "Expires:" in sec.text
