"""Güvenlik denetiminde (2026-11-04) testsiz bulunan kritik akışlar ve kapatılan bulgular."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from builders import minimal_docx
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from test_web import csrf_from, login, upload, wait_done
from thesis import thesis

from synora.web import worker
from synora.web.app import _hash, create_app
from synora.web.db import Database
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
RULESET = str(ROOT / "rulesets" / "example.yaml")
ALICE, BOB = "alice@beun.edu.tr", "bob@beun.edu.tr"


@pytest.fixture
def two(settings: Settings, mailer: ConsoleMailer) -> Iterator[tuple[TestClient, TestClient]]:
    app = create_app(settings, mailer)
    with TestClient(app) as alice, TestClient(app) as bob:
        yield alice, bob


def post_routes(client: TestClient) -> list[str]:
    """Uygulamanın POST rotaları: yeni eklenen rota kendiliğinden denetime girer."""
    return sorted(r.path for r in client.app.routes  # type: ignore[attr-defined]
                  if isinstance(r, APIRoute) and "POST" in r.methods)


def get_paths(client: TestClient) -> set[str]:
    return {r.path for r in client.app.routes  # type: ignore[attr-defined]
            if isinstance(r, APIRoute) and "GET" in r.methods}


# --- Yetki: başkasının işi ------------------------------------------------------------------------


JOB_REQUESTS = [
    ("GET", "", {}),
    ("GET", "/status", {}),
    ("GET", "/report.json", {}),
    ("POST", "/delete", {"form": True}),
    ("POST", "/roles", {"json": {"roles": {}}}),
    ("POST", "/feedback", {"form": True}),
    ("POST", "/recheck", {"content": b"x"}),
    ("POST", "/output/fixed", {"content": b"x"}),
    ("POST", "/output/annotated", {"content": b"x"}),
]


def test_every_job_route_is_covered_by_the_ownership_matrix(client: TestClient) -> None:
    covered = {
        f"/jobs/{{job_id}}{suffix}".replace("/fixed", "/{kind}").replace("/annotated", "/{kind}")
        for _, suffix, _ in JOB_REQUESTS
    }
    routes = {r.path for r in client.app.routes  # type: ignore[attr-defined]
              if isinstance(r, APIRoute) and r.path.startswith("/jobs/")}
    assert routes == covered


@pytest.mark.parametrize(("method", "suffix", "kw"), JOB_REQUESTS,
                         ids=[f"{m}{s or '/'}" for m, s, _ in JOB_REQUESTS])
def test_other_user_with_valid_token_gets_404_on_every_job_route(
    two: tuple[TestClient, TestClient], mailer: ConsoleMailer,
    method: str, suffix: str, kw: dict[str, Any],
) -> None:
    alice, bob = two
    job_id = upload(alice, login(alice, mailer, ALICE), thesis())
    wait_done(alice, job_id)
    token = login(bob, mailer, BOB)
    extra = dict(kw)
    if extra.pop("form", False):
        extra["data"] = {"csrf": token, "rule_id": "body.size_pt", "vote": "wrong"}
    res = bob.request(method, f"/jobs/{job_id}{suffix}", headers={"X-CSRF-Token": token}, **extra)
    assert res.status_code == 404
    assert alice.get(f"/jobs/{job_id}/status").status_code == 200  # iş yerinde duruyor


@pytest.mark.parametrize(("method", "suffix", "kw"), JOB_REQUESTS,
                         ids=[f"{m}{s or '/'}" for m, s, _ in JOB_REQUESTS])
def test_anonymous_never_reaches_a_job(
    two: tuple[TestClient, TestClient], mailer: ConsoleMailer,
    method: str, suffix: str, kw: dict[str, Any],
) -> None:
    alice, anonymous = two
    job_id = upload(alice, login(alice, mailer, ALICE), thesis())
    wait_done(alice, job_id)
    extra = {k: v for k, v in kw.items() if k != "form"}
    res = anonymous.request(method, f"/jobs/{job_id}{suffix}", follow_redirects=False, **extra)
    assert res.status_code in {303, 401, 403, 404}
    assert b"source_sha256" not in res.content


# --- CSRF: tüm POST rotaları ----------------------------------------------------------------------


def test_every_post_route_refuses_a_logged_in_request_without_token(
    client: TestClient, mailer: ConsoleMailer,
) -> None:
    job_id = upload(client, login(client, mailer), thesis())
    wait_done(client, job_id)
    routes = post_routes(client)
    assert len(routes) >= 20
    for path in routes:
        url = path.replace("{job_id}", job_id).replace("{kind}", "fixed")
        res = client.post(url, data={"x": "1"}, follow_redirects=False)
        # 404: yönetim rotaları yetkisize var olmadığını söyler.
        assert res.status_code in {400, 403, 404}, path
    assert client.get(f"/jobs/{job_id}").status_code == 200  # iş silinmedi
    assert client.get(f"/jobs/{job_id}/status").status_code == 200  # oturum kapanmadı


def test_state_changing_routes_do_not_answer_get(client: TestClient, mailer: ConsoleMailer) -> None:
    job_id = upload(client, login(client, mailer), thesis())
    wait_done(client, job_id)
    readable = get_paths(client)
    for path in post_routes(client):
        if path in readable:
            continue  # aynı adreste ayrıca form sayfası var (/kayit, /auth gibi)
        url = path.replace("{job_id}", job_id).replace("{kind}", "fixed")
        assert client.get(url, follow_redirects=False).status_code == 405, path
    assert client.get(f"/jobs/{job_id}").status_code == 200


def test_opening_login_link_with_get_does_not_consume_it(
    client: TestClient, mailer: ConsoleMailer,
) -> None:
    """E-posta tarayıcıları bağlantıyı önceden açar; GET onu tüketmemeli, oturum açmamalı."""
    res = client.post("/login", data={"email": ALICE, "csrf": csrf_from(client.get("/giris").text)})
    assert res.status_code == 200
    token = mailer.sent[-1][1].split("token=")[1]
    assert client.get(f"/auth?token={token}").status_code == 200
    assert client.get(f"/auth?token={token}").status_code == 200
    assert client.app.state.db.login_token_valid(_hash(token))  # type: ignore[attr-defined]
    assert "Son denetimler" not in client.get("/").text


# --- Saklama süresi temizliği ---------------------------------------------------------------------


def janitor_runner(tmp_path: Path, settings: Settings, wakes: int) -> worker.JobRunner:
    runner = worker.JobRunner(Database(tmp_path / "j.db"), settings)
    results = iter([False] * wakes + [True])
    runner._stop.wait = lambda _timeout=None: next(results)  # type: ignore[method-assign]
    return runner


def test_janitor_purges_with_configured_retention(tmp_path: Path, settings: Settings,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    runner = janitor_runner(tmp_path, settings, wakes=1)
    seen: list[float] = []
    monkeypatch.setattr(runner.db, "purge", lambda seconds: seen.append(seconds) or 0)
    runner._janitor()
    assert seen == [settings.retention_hours * 3600]


def test_janitor_survives_a_database_error(tmp_path: Path, settings: Settings,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    runner = janitor_runner(tmp_path, settings, wakes=2)
    calls: list[float] = []

    def purge(seconds: float) -> int:
        calls.append(seconds)
        if len(calls) == 1:
            raise sqlite3.OperationalError("disk full")
        return 0

    events: list[str] = []
    monkeypatch.setattr(runner.db, "purge", purge)
    monkeypatch.setattr(worker, "log_event", lambda event, **_: events.append(event))
    runner._janitor()
    assert len(calls) == 2
    assert events == ["retention.purge_failed"]


def test_deleting_a_report_leaves_nothing_in_the_wal(tmp_path: Path) -> None:
    db = Database(tmp_path / "d.db")
    db.add_job("silinecek-is-0000000001", ALICE, "example")
    db.finish_job("silinecek-is-0000000001", report='{"r": "GIZLI-RAPOR"}', error_code=None)
    db.delete_job("silinecek-is-0000000001")
    wal = tmp_path / "d.db-wal"
    assert not wal.exists() or wal.stat().st_size == 0
    assert b"GIZLI-RAPOR" not in (tmp_path / "d.db").read_bytes()


# --- Giriş bağlantıları ve ayarlar ----------------------------------------------------------------


def test_using_one_login_link_cancels_the_others(client: TestClient, mailer: ConsoleMailer) -> None:
    tokens = []
    for _ in range(2):
        page = client.get("/giris")
        res = client.post("/login", data={"email": ALICE, "csrf": csrf_from(page.text)})
        assert res.status_code == 200
        tokens.append(mailer.sent[-1][1].split("token=")[1])
    db = client.app.state.db  # type: ignore[attr-defined]
    assert db.consume_login_token(_hash(tokens[0]))
    assert not db.login_token_valid(_hash(tokens[1]))


def test_production_refuses_retention_beyond_the_promise(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "t.db", rulesets_dir=ROOT / "rulesets",
                        base_url="https://ornek.edu.tr", allowed_domains=("beun.edu.tr",),
                        dev=False, email_verification=False, retention_hours=1000.0)
    assert any("RETENTION" in problem for problem in settings.problems())
    allowed = replace(settings, retention_hours=24.0)
    assert not any("RETENTION" in problem for problem in allowed.problems())


def test_demo_registration_does_not_overwrite_an_existing_consent(tmp_path: Path) -> None:
    """Demo kipinde adres doğrulanmaz: başkası formu doldurup onay kanıtını değiştirememeli."""
    db = Database(tmp_path / "o.db")
    db.register_user(ALICE, "surum-1")
    first = db.user_consent(ALICE)
    time.sleep(0.01)
    db.register_user(ALICE, "surum-2")
    assert db.user_consent(ALICE) == first


def test_privacy_notice_says_cloudflare_opens_the_connection(client: TestClient) -> None:
    text = " ".join(client.get("/aydinlatma").text.split())
    assert "şifresi Cloudflare'de çözülür" in text
    assert "şifreli bağlantıyla Cloudflare ağından geçerek" not in text


def test_architecture_does_not_promise_no_third_party() -> None:
    doc = " ".join((ROOT / "docs" / "architecture.md").read_text(encoding="utf-8").split())
    assert "koşulda üçüncü tarafa gitmez" not in doc
    assert "TLS Cloudflare'de sonlanır" in doc


# --- Alt süreç yalıtımı ---------------------------------------------------------------------------


class FakeConn:
    def __init__(self, on_recv: Any) -> None:
        self.on_recv = on_recv
        self.sent: list[bytes] = []

    def recv_bytes(self) -> bytes:
        self.on_recv()
        return b"tez"

    def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    def close(self) -> None:
        pass


def test_child_clears_secrets_and_sets_limits_before_reading_the_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYNORA_SMTP_PASSWORD", "gizli")
    limits: list[int] = []
    if sys.platform != "win32":
        import resource

        monkeypatch.setattr(resource, "setrlimit", lambda kind, _value: limits.append(kind))
    state: dict[str, Any] = {}

    def on_recv() -> None:
        state["env"] = [k for k in os.environ if k.startswith("SYNORA_")]
        state["limits"] = list(limits)

    monkeypatch.setattr(worker, "run_pipeline", lambda *_: {})
    monkeypatch.setattr(worker, "encode_pipeline", lambda _: b"sonuc")
    conn = FakeConn(on_recv)
    worker._child(conn, "check", RULESET, "is-1", 30)  # type: ignore[arg-type]
    assert state["env"] == []
    assert conn.sent == [b"sonuc"]
    if sys.platform != "win32":
        import resource

        assert set(state["limits"]) >= {resource.RLIMIT_AS, resource.RLIMIT_CPU}


def test_oversized_child_message_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ele geçirilmiş alt süreç, üst sürece sınırsız veri yükleyememeli."""
    monkeypatch.setattr(worker, "MAX_CHILD_MESSAGE_BYTES", 8)
    assert worker._spawn("check", minimal_docx(), RULESET, "is-2", 60.0) == "INTERNAL"


# --- Dağıtım ayarları: "tez diske yazılmaz" ve "bağlantı loglanmaz" sözleri -----------------------


NGINX = (ROOT / "deploy" / "nginx-synora.conf").read_text(encoding="utf-8")
SERVICE = (ROOT / "deploy" / "synora.service").read_text(encoding="utf-8")


@pytest.mark.parametrize("needle", [
    "proxy_request_buffering off;",  # yüklenen tez geçici dosyaya yazılmaz
    'proxy_set_header CF-Connecting-IP "";',  # uydurulan istemci IP'si uygulamaya geçmez
    "proxy_set_header X-Real-IP $remote_addr;",
    "access_log /var/log/nginx/synora.access.log synora_noquery;",  # giriş bağlantısı loglanmaz
])
def test_nginx_keeps_its_promises(needle: str) -> None:
    assert needle in NGINX
    assert "$request_uri" not in NGINX.split("log_format synora_noquery")[1].split(";")[0]


@pytest.mark.parametrize("needle", ["proxy_buffering off;", "proxy_max_temp_file_size 0;"])
def test_nginx_does_not_spool_returned_theses_to_disk(needle: str) -> None:
    assert needle in NGINX


@pytest.mark.parametrize("line", [
    "NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=yes", "PrivateTmp=yes",
    "ReadWritePaths=/var/lib/synora", "UMask=0077", "User=synora",
])
def test_systemd_unit_stays_hardened(line: str) -> None:
    assert line in SERVICE.splitlines()
