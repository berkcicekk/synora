"""Denetimin düşük bulguları: oturum, hesap silme, kimlik özeti, alt süreç, dağıtım ayarları."""

from __future__ import annotations

import hashlib
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml
from builders import minimal_docx
from fastapi.testclient import TestClient
from test_web import csrf_from, login, upload, wait_done
from thesis import thesis

from synora.web import worker
from synora.web.app import SESSION_COOKIE, _hash, create_app
from synora.web.db import Database
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
RULESET = str(ROOT / "rulesets" / "example.yaml")
EMAIL = "ogrenci@beun.edu.tr"


@pytest.fixture
def demo_client(settings: Settings, mailer: ConsoleMailer) -> Iterator[TestClient]:
    with TestClient(create_app(replace(settings, email_verification=False), mailer)) as c:
        yield c


def sessions(client: TestClient) -> int:
    db = client.app.state.db  # type: ignore[attr-defined]
    return int(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])


# --- D2: oturumlar --------------------------------------------------------------------------------


def test_logging_in_again_ends_the_old_session(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    old = client.cookies.get(SESSION_COOKIE)
    assert sessions(client) == 1
    db = client.app.state.db  # type: ignore[attr-defined]
    db.add_login_token(_hash("ikinci-baglanti"), EMAIL, 600)
    page = client.get("/auth?token=ikinci-baglanti")
    res = client.post("/auth", data={"token": "ikinci-baglanti", "csrf": csrf_from(page.text)},
                      follow_redirects=False)
    assert res.status_code == 303
    assert sessions(client) == 1
    assert client.cookies.get(SESSION_COOKIE) != old


def test_logout_everywhere_ends_all_sessions(settings: Settings, mailer: ConsoleMailer) -> None:
    app = create_app(settings, mailer)
    with TestClient(app) as phone, TestClient(app) as laptop:
        login(phone, mailer)
        csrf = login(laptop, mailer)
        assert sessions(laptop) == 2
        res = laptop.post("/logout", data={"csrf": csrf, "all": "1"}, follow_redirects=False)
        assert res.status_code == 303
        assert sessions(laptop) == 0
        assert "Son denetimler" not in phone.get("/").text


def test_plain_logout_keeps_other_devices(settings: Settings, mailer: ConsoleMailer) -> None:
    app = create_app(settings, mailer)
    with TestClient(app) as phone, TestClient(app) as laptop:
        login(phone, mailer)
        csrf = login(laptop, mailer)
        laptop.post("/logout", data={"csrf": csrf}, follow_redirects=False)
        assert "Son denetimler" in phone.get("/").text


def test_demo_mode_cannot_end_other_peoples_sessions(demo_client: TestClient,
                                                     settings: Settings) -> None:
    """Demo kipinde adres doğrulanmaz: "her yerden çık" başkasını da düşürürdü."""
    db = demo_client.app.state.db  # type: ignore[attr-defined]
    db.add_session("baskasi", EMAIL, "csrf", 3600)
    demo_client.post("/kayit", data={
        "email": EMAIL, "kvkk": "1", "csrf": csrf_from(demo_client.get("/kayit").text)})
    html = demo_client.get("/").text
    assert "Tüm cihazlardan çık" not in html and "Hesabımı sil" not in html
    demo_client.post("/logout", data={"csrf": csrf_from(html), "all": "1"},
                     follow_redirects=False)
    assert db.execute("SELECT COUNT(*) FROM sessions WHERE id_hash='baskasi'").fetchone()[0] == 1


# --- D10: hesabını silme --------------------------------------------------------------------------


def test_panel_offers_account_controls(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    html = client.get("/").text
    assert "Tüm cihazlardan çık" in html and "Hesabımı sil" in html
    assert 'action="/hesap/sil"' in html


def test_user_can_delete_own_account(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, thesis())
    wait_done(client, job_id)
    res = client.post("/hesap/sil", data={"csrf": csrf, "confirm": EMAIL},
                      follow_redirects=False)
    assert res.status_code == 303
    db = client.app.state.db  # type: ignore[attr-defined]
    assert db.user_consent(EMAIL) is None
    assert db.get_job(job_id) is None
    assert sessions(client) == 0
    assert "Son denetimler" not in client.get("/").text


@pytest.mark.parametrize("confirm", ["", "yanlis@beun.edu.tr"])
def test_account_is_kept_without_correct_confirmation(client: TestClient, mailer: ConsoleMailer,
                                                      confirm: str) -> None:
    csrf = login(client, mailer)
    res = client.post("/hesap/sil", data={"csrf": csrf, "confirm": confirm},
                      follow_redirects=False)
    assert res.status_code == 400
    assert client.app.state.db.user_consent(EMAIL) is not None  # type: ignore[attr-defined]


def test_account_delete_needs_csrf_and_login(client: TestClient, mailer: ConsoleMailer) -> None:
    assert client.post("/hesap/sil", data={"confirm": EMAIL},
                       follow_redirects=False).status_code in {401, 403, 303}
    login(client, mailer)
    res = client.post("/hesap/sil", data={"csrf": "yanlis", "confirm": EMAIL},
                      follow_redirects=False)
    assert res.status_code == 403
    assert client.app.state.db.user_consent(EMAIL) is not None  # type: ignore[attr-defined]


def test_account_delete_is_closed_in_demo_mode(demo_client: TestClient) -> None:
    """Demo kipinde başkasının adresiyle girilebilir: hesabı silme kapalıdır."""
    demo_client.post("/kayit", data={
        "email": EMAIL, "kvkk": "1", "csrf": csrf_from(demo_client.get("/kayit").text)})
    html = demo_client.get("/").text
    res = demo_client.post("/hesap/sil", data={"csrf": csrf_from(html), "confirm": EMAIL},
                           follow_redirects=False)
    assert res.status_code == 404
    assert demo_client.app.state.db.user_consent(EMAIL) is not None  # type: ignore[attr-defined]


def test_privacy_notice_mentions_self_delete_only_when_available(
    client: TestClient, demo_client: TestClient,
) -> None:
    assert "Hesabımı sil" in client.get("/aydinlatma").text
    assert "Hesabımı sil" not in demo_client.get("/aydinlatma").text


# --- D5: kimlik özeti -----------------------------------------------------------------------------


def test_identity_hash_cannot_be_recomputed_from_the_address(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.db")
    assert db.identity_hash(EMAIL) != hashlib.sha256(EMAIL.encode()).hexdigest()[:16]
    assert len(db.identity_hash(EMAIL)) == 16


def test_identity_hash_is_stable_across_restarts_and_differs_per_install(tmp_path: Path) -> None:
    first = Database(tmp_path / "a.db").identity_hash(EMAIL)
    assert Database(tmp_path / "a.db").identity_hash(EMAIL) == first
    assert Database(tmp_path / "b.db").identity_hash(EMAIL) != first


def test_account_delete_erases_old_style_log_targets(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.db")
    db.register_user(EMAIL, "surum")
    old = hashlib.sha256(EMAIL.encode()).hexdigest()[:16]
    db.set_suspended(EMAIL, True, actor="yonetici", target=old)
    db.delete_account(EMAIL, actor="yonetici", target=db.identity_hash(EMAIL))
    targets = [row[3] for row in db.admin_log()]
    assert old not in targets and db.identity_hash(EMAIL) not in targets


def test_app_logs_identity_hash_not_plain_digest() -> None:
    source = (ROOT / "src" / "synora" / "web" / "app.py").read_text(encoding="utf-8")
    assert "target=_hash(" not in source
    assert "hash=_hash(" not in source


# --- D8: yeniden denetim yarışı -------------------------------------------------------------------


def test_requeue_succeeds_only_once(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.db")
    db.add_job("is-0000000000000000001", EMAIL, "example")
    db.finish_job("is-0000000000000000001", report="{}", error_code=None)
    assert db.requeue("is-0000000000000000001") is True
    assert db.requeue("is-0000000000000000001") is False


# --- D6, D9: alt süreç ----------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="kaynak sınırları yalnız POSIX")
def test_child_limits_block_core_dumps_and_file_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    import resource

    seen: dict[int, tuple[int, int]] = {}
    monkeypatch.setattr(resource, "setrlimit", lambda kind, value: seen.__setitem__(kind, value))
    undumpable: list[bool] = []
    monkeypatch.setattr(worker, "_make_undumpable", lambda: undumpable.append(True))
    worker._apply_child_limits(30)
    assert seen[resource.RLIMIT_CORE] == (0, 0)
    assert seen[resource.RLIMIT_FSIZE] == (0, 0)
    assert seen[resource.RLIMIT_CPU] == (30, 30)
    assert seen[resource.RLIMIT_AS] == (worker.MEMORY_LIMIT_BYTES, worker.MEMORY_LIMIT_BYTES)
    assert undumpable == [True]


@pytest.mark.skipif(sys.platform == "win32", reason="kaynak sınırları yalnız POSIX")
def test_real_child_still_works_under_the_limits() -> None:
    assert isinstance(worker._spawn("check", minimal_docx(), RULESET, "is-3", 60.0), bytes)


class FakeProcess:
    def __init__(self, conn: FakeParent) -> None:
        self.conn = conn
        self.killed = False

    def start(self) -> None:
        pass

    def join(self, _timeout: float | None = None) -> None:
        pass

    def is_alive(self) -> bool:
        return not self.killed

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        self.killed = True
        self.conn.dead.set()


class FakeParent:
    """Mesajı yarım bırakan süreç: okuma, süreç öldürülene kadar takılır."""

    def __init__(self) -> None:
        self.dead = threading.Event()

    def send_bytes(self, _data: bytes) -> None:
        pass

    def poll(self, _timeout: float) -> bool:
        return True

    def recv_bytes(self, _limit: int) -> bytes:
        if not self.dead.wait(5):
            raise AssertionError("süreç öldürülmedi")
        raise EOFError

    def close(self) -> None:
        pass


def test_stuck_child_message_is_killed_at_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = FakeParent()
    process = FakeProcess(parent)

    class FakeContext:
        def Pipe(self) -> tuple[Any, Any]:
            return parent, parent

        def Process(self, **_kw: Any) -> FakeProcess:
            return process

    monkeypatch.setattr(worker.mp, "get_context", lambda _name: FakeContext())
    monkeypatch.setattr(worker, "CHILD_KILL_GRACE_SECONDS", 0.05)
    started = time.monotonic()
    assert worker._spawn("check", b"x", RULESET, "is-4", 0.05) == "INTERNAL"
    assert process.killed and time.monotonic() - started < 4


def test_surviving_child_is_killed_after_terminate(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = FakeParent()
    parent.poll = lambda _timeout: False  # type: ignore[method-assign]
    process = FakeProcess(parent)

    class FakeContext:
        def Pipe(self) -> tuple[Any, Any]:
            return parent, parent

        def Process(self, **_kw: Any) -> FakeProcess:
            return process

    monkeypatch.setattr(worker.mp, "get_context", lambda _name: FakeContext())
    assert worker._spawn("check", b"x", RULESET, "is-5", 0.05) == "TIMEOUT"
    assert process.killed


# --- D6, D7, D11: dağıtım ayarları ----------------------------------------------------------------


SERVICE = (ROOT / "deploy" / "synora.service").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("line", [
    "LimitCORE=0", "MemorySwapMax=0", "ProtectProc=invisible", "CapabilityBoundingSet=",
    "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6", "RestrictNamespaces=yes",
    "SystemCallArchitectures=native", "SystemCallFilter=@system-service",
])
def test_systemd_unit_has_extra_hardening(line: str) -> None:
    assert line in SERVICE


def test_container_has_no_core_dumps_or_swap() -> None:
    service = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    conf = service["services"]["synora"]
    assert conf["ulimits"]["core"] == 0
    assert conf["memswap_limit"] == conf["mem_limit"]


def test_ci_audits_dependencies() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "pip-audit==" in workflow and "uv export --frozen" in workflow
    dependabot = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    assert {u["package-ecosystem"] for u in dependabot["updates"]} == {"uv", "github-actions"}


def test_deploy_docs_describe_client_ip_correctly() -> None:
    readme = " ".join((ROOT / "deploy" / "README.md").read_text(encoding="utf-8").split())
    assert "Uygulama istemci IP'sini kullanmadığından" not in readme
    assert "SYNORA_CLIENT_IP_HEADER" in readme
    assert "yalnızca öndeki vekil" in readme


def test_login_token_lookup_still_uses_plain_token_hash() -> None:
    assert _hash("x") == hashlib.sha256(b"x").hexdigest()
