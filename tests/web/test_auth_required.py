"""Yükleme ve denetim uç noktaları oturum ister; oturumsuz istekte gövde (tez) hiç okunmaz.

TestClient gövdeyi uygulamaya vermeden önce kendisi okuyabildiği için "gövde okunmadı"
iddiası ASGI düzeyinde sınanır: uygulama doğrudan çağrılır, receive() çağrıları sayılır.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_web import bad_thesis, login, upload, wait_done

from synora.web.app import create_app
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

JOB = "aaaaaaaaaaaaaaaaaaaaaaaa"
ENDPOINTS = [
    ("/jobs", "application/octet-stream"),
    (f"/jobs/{JOB}/output/fixed", "application/octet-stream"),
    (f"/jobs/{JOB}/output/annotated", "application/octet-stream"),
    (f"/jobs/{JOB}/recheck", "application/octet-stream"),
    (f"/jobs/{JOB}/roles", "application/json"),
    (f"/jobs/{JOB}/feedback", "application/x-www-form-urlencoded"),
]


def _call(app: Any, path: str, content_type: str) -> tuple[int, int]:
    """POST isteğini ASGI ile gönderir; (durum kodu, gövde için receive çağrısı sayısı) döner."""
    body = b"PK\x03\x04" + b"0" * 4096  # tez gibi görünen gövde
    reads = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
        "headers": [(b"host", b"testserver"), (b"content-type", content_type.encode()),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-csrf-token", b"x"), (b"x-ruleset", b"example")],
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], reads


@pytest.mark.parametrize(("path", "content_type"), ENDPOINTS)
def test_upload_endpoints_reject_without_session_before_reading_body(
        settings: Settings, mailer: ConsoleMailer, path: str, content_type: str) -> None:
    app = create_app(settings, mailer)
    status, reads = _call(app, path, content_type)
    # Arayüzün fetch ile çağırdığı uçlar 401 JSON, diğerleri girişsiz ana sayfaya yönlendirme.
    assert status in (401, 303), (path, status)
    assert reads == 0, f"{path}: oturumsuz istekte gövde okundu ({reads} kez)"


def test_upload_without_session_returns_401_json(client: TestClient) -> None:
    res = client.post("/jobs", content=bad_thesis(), headers={
        "X-CSRF-Token": "x", "X-Ruleset": "example", "Content-Type": "application/octet-stream"})
    assert res.status_code == 401
    assert "Oturumunuz sona erdi" in res.json()["error"]


def test_upload_with_session_still_works(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, bad_thesis())
    assert wait_done(client, job_id) == "done"
    assert client.get(f"/jobs/{job_id}").status_code == 200


def test_read_counter_detects_body_reads(settings: Settings, mailer: ConsoleMailer) -> None:
    """Ölçüm aracının kendisi: gövdeyi okuyan bir uçta (girişsiz /login formu) sayaç artar.
    Bu olmadan yukarıdaki "0 okuma" iddiası hiçbir şey kanıtlamazdı."""
    app = create_app(settings, mailer)
    _, reads = _call(app, "/login", "application/x-www-form-urlencoded")
    assert reads >= 1
