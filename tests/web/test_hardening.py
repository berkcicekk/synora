"""Güvenlik taramasının düşük öncelikli bulguları: her biri bir davranış olarak sabitlenir."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_web import bad_thesis, csrf_from, login, upload, wait_done

import synora.web.app as app_module
from synora.web.app import client_network, create_app
from synora.web.db import ERASED_TARGET, Database
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings
from synora.web.worker import scrub_environment

STUDENT = "ogrenci@beun.edu.tr"
ADMIN = "yonetici@beun.edu.tr"
ACTOR = "yonetici-ozeti"


@pytest.fixture
def demo_client(settings: Settings, mailer: ConsoleMailer) -> Iterator[TestClient]:
    configured = replace(settings, email_verification=False, admin_emails=(ADMIN,),
                         admin_key_sha256=hashlib.sha256(b"anahtar").hexdigest())
    with TestClient(create_app(configured, mailer)) as c:
        yield c


def db_of(client: TestClient) -> Database:
    return client.app.state.db  # type: ignore[attr-defined,no-any-return]


def demo_register(client: TestClient, email: str = STUDENT) -> Any:
    page = client.get("/kayit")
    return client.post("/kayit", data={"email": email, "csrf": csrf_from(page.text), "kvkk": "1"},
                       follow_redirects=False)


def demo_login(client: TestClient, email: str = STUDENT) -> Any:
    page = client.get("/giris")
    return client.post("/login", data={"email": email, "csrf": csrf_from(page.text)},
                       follow_redirects=False)


def request_login_link(client: TestClient, email: str = STUDENT) -> Any:
    page = client.get("/giris")
    return client.post("/login", data={"email": email, "csrf": csrf_from(page.text)})


# --- CSRF değeri ----------------------------------------------------------------------------------


def test_non_ascii_csrf_is_rejected_not_crashed(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    res = client.post("/logout", content="csrf=%C3%A9", headers={
        "Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    assert res.status_code == 403


def test_non_ascii_csrf_on_login_form_is_rejected_not_crashed(client: TestClient) -> None:
    client.get("/giris")
    res = client.post("/login", content=f"email={STUDENT}&csrf=%C3%A9", headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    assert res.status_code == 403


# --- Yüklemeyle yarışan silme ---------------------------------------------------------------------


def test_upload_is_dropped_if_session_ended_during_read(client: TestClient, mailer: ConsoleMailer,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    csrf = login(client, mailer)
    db = db_of(client)
    real = app_module.read_body

    async def ends_session_midway(*args: Any, **kw: Any) -> bytes:
        body = await real(*args, **kw)
        db.end_sessions(STUDENT, actor=ACTOR, target="hedef")
        return body

    monkeypatch.setattr(app_module, "read_body", ends_session_midway)
    res = client.post("/jobs", content=bad_thesis(), headers={
        "X-CSRF-Token": csrf, "X-Ruleset": "example",
        "Content-Type": "application/octet-stream"})
    assert res.status_code == 401
    assert db.recent_jobs(STUDENT) == []


# --- Demo kipi: oturuma bağlı iş ------------------------------------------------------------------


def test_upload_page_hides_jobs_of_other_sessions(demo_client: TestClient) -> None:
    owner = TestClient(demo_client.app)
    assert demo_register(owner).status_code == 303
    up = owner.get("/yukle")
    job_id = upload(owner, csrf_from(up.text.split('id="upload"')[1]), bad_thesis())
    assert wait_done(owner, job_id) == "done"
    assert f'/jobs/{job_id}"' in owner.get("/yukle").text

    other = TestClient(demo_client.app)  # aynı adresi bilen başka tarayıcı
    assert demo_login(other).status_code == 303
    assert f'/jobs/{job_id}"' not in other.get("/yukle").text


# --- Geri bildirim --------------------------------------------------------------------------------


def vote(client: TestClient, csrf: str, job_id: str, **data: str) -> int:
    return client.post(f"/jobs/{job_id}/feedback", data={"verdict": "wrong", **data},
                       headers={"X-CSRF-Token": csrf}).status_code


def test_feedback_must_match_a_finding_in_the_report(client: TestClient,
                                                     mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, bad_thesis())
    assert wait_done(client, job_id) == "done"
    db = db_of(client)
    report = json.loads(db.get_job(job_id).report)  # type: ignore[arg-type,union-attr]
    finding = next(f for f in report["findings"] if f["para_id"])
    rule, para = finding["rule_id"], finding["para_id"]

    assert vote(client, csrf, job_id, rule_id="body.uydurma") == 400
    assert vote(client, csrf, job_id, rule_id=rule, para_id="p999999") == 400
    assert db.execute("SELECT COUNT(*) FROM feedback_counts").fetchone()[0] == 0
    assert vote(client, csrf, job_id, rule_id=rule, para_id=para) == 200
    assert vote(client, csrf, job_id, rule_id=rule) == 200  # kart oyu: paragrafsız


# --- Giriş bağlantısı -----------------------------------------------------------------------------


def test_confirm_page_names_the_account(client: TestClient, mailer: ConsoleMailer) -> None:
    request_login_link(client)
    token = mailer.sent[-1][1].split("token=")[1]
    page = client.get(f"/auth?token={token}").text
    assert STUDENT in page and "sizin değilse" in page


def test_suspended_account_gets_same_answer_without_mail(client: TestClient,
                                                         mailer: ConsoleMailer) -> None:
    db = db_of(client)
    db.register_user(STUDENT, "test")
    db.set_suspended(STUDENT, True, actor=ACTOR, target="hedef")
    res = request_login_link(client)
    assert res.status_code == 200 and "E-postanızı kontrol edin" in res.text
    assert mailer.sent == []


def test_demo_login_is_not_locked_by_requests_from_others(demo_client: TestClient,
                                                          settings: Settings) -> None:
    assert demo_register(TestClient(demo_client.app)).status_code == 303
    for _ in range(settings.login_requests_per_hour):
        assert demo_login(TestClient(demo_client.app)).status_code == 303
    assert demo_login(TestClient(demo_client.app)).status_code == 303


# --- Yönetici adresi demo kipinde belli olmaz ---------------------------------------------------


def test_demo_session_with_admin_address_sees_no_admin_link(demo_client: TestClient) -> None:
    assert demo_register(demo_client, ADMIN).status_code == 303
    assert 'href="/yonetim"' not in demo_client.get("/").text


# --- İşlem kaydı ----------------------------------------------------------------------------------


def test_delete_erases_target_hash_from_admin_log(tmp_path: Path) -> None:
    db = Database(tmp_path / "d.db")
    db.register_user(STUDENT, "test")
    db.register_user(ADMIN, "test")
    db.add_session("oturum", STUDENT, "csrf", 3600)
    db.add_session("baska", ADMIN, "csrf", 3600)
    db.end_sessions(STUDENT, actor=ACTOR, target="ogrenci-ozeti")
    db.end_sessions(ADMIN, actor=ACTOR, target="baska-ozet")
    assert db.delete_account(STUDENT, actor=ACTOR, target="ogrenci-ozeti")
    targets = {r[2]: r[3] for r in db.admin_log() if r[2] == "account_delete"}
    assert targets == {"account_delete": ERASED_TARGET}
    logged = str(db.admin_log())
    assert "ogrenci-ozeti" not in logged and "baska-ozet" in logged


# --- İstemci ağı ----------------------------------------------------------------------------------


@pytest.mark.parametrize(("ip", "expected"), [
    ("203.0.113.9", "203.0.113.9"),
    ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
    ("2001:db8:1:2:1111:2222:3333:4444", "2001:db8:1:2::/64"),
    ("gecersiz", "gecersiz"),
])
def test_client_network_groups_ipv6_by_64(ip: str, expected: str) -> None:
    assert client_network(ip) == expected


def test_ipv6_addresses_share_login_limit(settings: Settings, mailer: ConsoleMailer) -> None:
    limited = replace(settings, login_requests_per_ip_hour=1)
    with TestClient(create_app(limited, mailer)) as c:
        page = c.get("/giris")
        csrf = csrf_from(page.text)
        statuses = [c.post("/login", data={"email": f"k{i}@beun.edu.tr", "csrf": csrf},
                           headers={"cf-connecting-ip": f"2001:db8:1:2::{i + 1}"}).status_code
                    for i in range(2)]
    assert statuses == [200, 429]


# --- Alt süreç ortamı -----------------------------------------------------------------------------


def test_child_environment_has_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNORA_SMTP_PASSWORD", "gizli")
    monkeypatch.setenv("PATH_DENEME", "kalir")
    scrub_environment()
    assert "SYNORA_SMTP_PASSWORD" not in os.environ
    assert os.environ["PATH_DENEME"] == "kalir"
