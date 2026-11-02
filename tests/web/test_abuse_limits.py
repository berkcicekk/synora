"""Web sınırları: kopya kotası, 408 cezası, form süresi, büyük belge görünümü, alt süreç iletisi."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from builders import p, r
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect
from test_web import bad_thesis, csrf_from, login, output, upload, wait_done
from thesis import front_matter, main_matter, thesis

from synora.web import pipeline
from synora.web.app import RateLimiter, client_network, create_app
from synora.web.limits import read_body
from synora.web.mailer import ConsoleMailer
from synora.web.pipeline import run_pipeline
from synora.web.settings import Settings
from synora.web.worker import (
    MEMORY_LIMIT_BYTES,
    decode_output,
    decode_pipeline,
    encode_output,
    encode_pipeline,
)

ROOT = Path(__file__).resolve().parents[2]
RULESET = str(ROOT / "rulesets" / "zbeu-tip.yaml")
ADMIN = "yonetici@beun.edu.tr"
KEY = "dogru-anahtar-0123456789abcdef"


# --- Kopya kotası ---------------------------------------------------------------------------------


def test_copies_are_limited_per_account(settings: Settings, mailer: ConsoleMailer) -> None:
    with TestClient(create_app(replace(settings, copies_per_hour=2), mailer)) as client:
        csrf = login(client, mailer)
        data = bad_thesis()
        job_id = upload(client, csrf, data)
        assert wait_done(client, job_id) == "done"
        assert output(client, csrf, job_id, "fixed", data).status_code == 200
        assert output(client, csrf, job_id, "annotated", data).status_code == 200
        limited = output(client, csrf, job_id, "fixed", data)
        assert limited.status_code == 429 and "çok fazla kopya" in limited.json()["error"]


def test_recheck_shares_copy_quota(settings: Settings, mailer: ConsoleMailer) -> None:
    with TestClient(create_app(replace(settings, copies_per_hour=0), mailer)) as client:
        csrf = login(client, mailer)
        data = bad_thesis()
        job_id = upload(client, csrf, data)
        assert wait_done(client, job_id) == "done"
        res = client.post(f"/jobs/{job_id}/recheck", content=data, headers={
            "X-CSRF-Token": csrf, "Content-Type": "application/octet-stream"})
        assert res.status_code == 429


# --- Yükleme süresi cezası ------------------------------------------------------------------------


def test_rate_limiter_exhausted_does_not_consume() -> None:
    limiter = RateLimiter(2, 100)
    assert not limiter.exhausted("a", now=1000.0)
    assert not limiter.exhausted("a", now=1000.0)
    assert limiter.allow("a", now=1000.0) and limiter.allow("a", now=1000.0)
    assert limiter.exhausted("a", now=1000.0)
    assert not limiter.exhausted("a", now=1000.0 + 3601)


def test_repeated_upload_timeouts_are_penalized(settings: Settings,
                                                 mailer: ConsoleMailer) -> None:
    s = replace(settings, upload_grace_seconds=0, upload_max_seconds=0, upload_timeouts_per_hour=2)
    with TestClient(create_app(s, mailer)) as client:
        csrf = login(client, mailer)
        headers = {"X-CSRF-Token": csrf, "X-Ruleset": "example",
                    "Content-Type": "application/octet-stream"}
        codes = [client.post("/jobs", content=bad_thesis(), headers=headers).status_code
                 for _ in range(3)]
    assert codes == [408, 408, 429]


def test_client_disconnect_is_a_quiet_client_error() -> None:
    async def gone() -> Any:
        raise ClientDisconnect
        yield b""  # üreteç olsun diye

    async def scenario() -> bytes:
        return await read_body(gone(), max_bytes=10, grace_seconds=1, min_bytes_per_second=1,
                               max_seconds=1)

    with pytest.raises(Exception, match="400") as exc:
        asyncio.run(scenario())
    assert getattr(exc.value, "status_code", None) == 400


# --- Form gövdesi süreli --------------------------------------------------------------------------


def test_form_body_has_a_deadline(settings: Settings, mailer: ConsoleMailer,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    import synora.web.app as app_module

    real = app_module.read_body

    async def spy(stream: Any, **kw: Any) -> bytes:
        captured.update(kw)
        return await real(stream, **kw)

    monkeypatch.setattr(app_module, "read_body", spy)
    with TestClient(create_app(settings, mailer)) as client:
        page = client.get("/giris")
        client.post("/login", data={"email": "ogrenci@beun.edu.tr", "csrf": csrf_from(page.text)})
    assert captured["max_bytes"] == 8 * 1024 and captured["max_seconds"] <= 10


# --- IPv4 eşlemeli adres --------------------------------------------------------------------------


def test_ipv4_mapped_addresses_keep_their_identity() -> None:
    assert client_network("::ffff:1.2.3.4") == "1.2.3.4"
    assert client_network("::ffff:9.9.9.9") == "9.9.9.9"


# --- Belge görünümü sınırı ------------------------------------------------------------------------


def test_huge_document_report_has_no_page_view(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "MAX_REPORT_BLOCKS", 5)
    outcome = run_pipeline(bad_thesis(), RULESET)
    assert outcome["report"]
    report = json.loads(outcome["report"])
    assert report["document"] == []
    assert all(f["block"] is None for f in report["findings"])


def test_document_view_kept_under_limit() -> None:
    outcome = run_pipeline(bad_thesis(), RULESET)
    assert outcome["report"] and json.loads(outcome["report"])["document"]


def test_page_without_document_view_explains_itself(client: TestClient,
                                                    mailer: ConsoleMailer) -> None:
    job_id = upload(client, login(client, mailer), bad_thesis())
    assert wait_done(client, job_id) == "done"
    db = client.app.state.db  # type: ignore[attr-defined]
    report = json.loads(db.get_job(job_id).report)
    report["document"] = []
    db.execute("UPDATE jobs SET report=? WHERE id=?", (json.dumps(report), job_id))
    html = client.get(f"/jobs/{job_id}").text
    assert "belge görünümü gösterilmiyor" in html and "eski biçimde" not in html


# --- Demo kipinde yönetici adresi ---------------


def demo_register(client: TestClient, email: str) -> None:
    page = client.get("/kayit")
    res = client.post("/kayit", data={"email": email, "csrf": csrf_from(page.text), "kvkk": "1"},
                      follow_redirects=False)
    assert res.status_code == 303


def test_demo_key_form_does_not_reveal_admin(settings: Settings, mailer: ConsoleMailer) -> None:
    s = replace(settings, email_verification=False, admin_emails=(ADMIN,),
                admin_key_sha256=hashlib.sha256(KEY.encode()).hexdigest())
    with TestClient(create_app(s, mailer)) as app_client:
        student = TestClient(app_client.app)
        demo_register(student, "ogrenci@beun.edu.tr")
        admin = TestClient(app_client.app)
        demo_register(admin, ADMIN)
        for c in (student, admin):
            page = c.get("/yonetim")
            assert page.status_code == 200 and 'name="key"' in page.text

        def unlock(c: TestClient, key: str) -> Any:
            csrf = csrf_from(c.get("/yonetim").text.split("admin-key-form")[1])
            return c.post("/yonetim/anahtar", data={"key": key, "csrf": csrf},
                          follow_redirects=False)

        wrong = unlock(student, KEY)  # doğru anahtar bile listede olmayanı açmaz
        assert wrong.status_code == 400 and "Anahtar yanlış" in wrong.text
        assert "Kayıtlı hesap" not in student.get("/yonetim").text
        assert unlock(admin, KEY).status_code == 303
        assert "Kayıtlı hesap" in admin.get("/yonetim").text


def test_verified_mode_still_hides_key_form_from_students(settings: Settings,
                                                          mailer: ConsoleMailer) -> None:
    s = replace(settings, admin_emails=(ADMIN,),
                admin_key_sha256=hashlib.sha256(KEY.encode()).hexdigest())
    with TestClient(create_app(s, mailer)) as client:
        login(client, mailer)
        assert client.get("/yonetim").status_code == 404


def test_demo_without_admin_settings_has_no_key_form(settings: Settings,
                                                     mailer: ConsoleMailer) -> None:
    with TestClient(create_app(replace(settings, email_verification=False), mailer)) as client:
        demo_register(client, "ogrenci@beun.edu.tr")
        assert client.get("/yonetim").status_code == 404


# --- Alt süreç iletisi ----------------------------------------------------------------------------


def test_pipeline_message_round_trip() -> None:
    result: dict[str, Any] = {"report": "{}", "stats": "{}", "error_code": None,
                              "source_sha256": "ab", "training": [("f", "body", "r")]}
    decoded = decode_pipeline(encode_pipeline(result))  # type: ignore[arg-type]
    assert decoded["report"] == "{}" and decoded["training"] == [("f", "body", "r")]


@pytest.mark.parametrize("message", [b"cop", b"[1, 2]", b'{"report": 5}', b"\x80\x04.",
                                     b'{"report": null}'])
def test_malformed_pipeline_message_is_internal_error(message: bytes) -> None:
    decoded = decode_pipeline(message)
    assert decoded["report"] is None and decoded["error_code"] == "INTERNAL"


def test_output_message_round_trip() -> None:
    assert decode_output(encode_output({"docx": b"PK\x03\x04", "error_code": None})) == {
        "docx": b"PK\x03\x04", "error_code": None}
    assert decode_output(encode_output({"docx": None, "error_code": "NOTHING_TO_FIX"})) == {
        "docx": None, "error_code": "NOTHING_TO_FIX"}


@pytest.mark.parametrize("message", [b"", b"X123", b"E" + b"a" * 200, b"E\xff\xfe"])
def test_malformed_output_message_is_internal_error(message: bytes) -> None:
    assert decode_output(message) == {"docx": None, "error_code": "INTERNAL"}


def test_isolated_child_never_unpickles() -> None:
    source = (ROOT / "src/synora/web/worker.py").read_text(encoding="utf-8")
    assert not re.search(r"\.recv\(|\.send\(", source)


# --- Bellek bütçesi -------------------------------------------------------------------------------


def test_memory_budget_counts_transient_copies() -> None:
    s = Settings()
    uploads = 2 * s.max_uploads_in_flight * s.max_upload_bytes  # parçalar + birleştirilmiş kopya
    copies = 2 * s.workers * s.max_upload_bytes  # giden dosya + dönen kopya
    base = 300 * 1024**2
    children = s.workers * MEMORY_LIMIT_BYTES
    assert uploads + s.max_queued_bytes + copies + base + children < 6 * 1024**3


# --- Tam akış: bozuk değerli belge işi düşürmez --------------------------------------------------


@pytest.mark.parametrize("ppr", [
    f'<w:spacing w:line="{"9" * 400}"/>',
    f'<w:ind w:firstLine="{"9" * 5000}"/>',
], ids=["satir-araligi", "girinti"])
def test_absurd_values_do_not_crash_pipeline(ppr: str) -> None:
    bad = p(r("Uzun bir gövde paragrafı metni burada."), ppr=ppr)
    body = front_matter() + main_matter(extra=bad)
    outcome = run_pipeline(thesis(body), RULESET)
    assert outcome["error_code"] is None


def test_surrogate_symbol_does_not_crash_pipeline() -> None:
    heading = '<w:p><w:r><w:sym w:font="Symbol" w:char="D800"/></w:r></w:p>'
    outcome = run_pipeline(thesis(front_matter() + main_matter(extra=heading)), RULESET)
    assert outcome["error_code"] is None and outcome["report"]
    assert json.loads(outcome["report"])
