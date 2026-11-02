"""Kaynak sınırları: yavaş yükleme yuva kilitleyemez, toplam bellek konteyner tavanını aşamaz."""

from __future__ import annotations

import asyncio
import re
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_web import bad_thesis, login, output, upload, wait_done

from synora.web.app import create_app
from synora.web.db import Database
from synora.web.limits import SlotCounter, read_body
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings
from synora.web.worker import MEMORY_LIMIT_BYTES, JobRunner, NoProcessSlot

ROOT = Path(__file__).resolve().parents[2]


async def stream_of(*chunks: bytes, delay: float = 0.0) -> AsyncIterator[bytes]:
    for chunk in chunks:
        await asyncio.sleep(delay)
        yield chunk


def read(stream: AsyncIterator[bytes], *, max_bytes: int = 100, grace: float = 0.05,
         min_rate: int = 1000, max_seconds: float = 1.0) -> bytes:
    return asyncio.run(read_body(stream, max_bytes=max_bytes, grace_seconds=grace,
                                 min_bytes_per_second=min_rate, max_seconds=max_seconds))


# --- Gövde okuma ----------------------------------------------------------------------------------


def test_read_body_joins_chunks() -> None:
    assert read(stream_of(b"ab", b"cd")) == b"abcd"


def test_read_body_rejects_oversize() -> None:
    with pytest.raises(HTTPException) as exc:
        read(stream_of(b"x" * 60, b"y" * 60))
    assert exc.value.status_code == 413


def test_read_body_times_out_when_client_goes_silent() -> None:
    with pytest.raises(HTTPException) as exc:
        read(stream_of(b"a", delay=0.2))
    assert exc.value.status_code == 408


def test_read_body_times_out_on_trickle() -> None:
    # Her parça bir öncekinin kazandırdığı süreyi aşar: kilitlemek için damla damla gönderim.
    with pytest.raises(HTTPException) as exc:
        read(stream_of(*[b"a"] * 50, delay=0.02), min_rate=1000)
    assert exc.value.status_code == 408


def test_read_body_lets_steady_upload_outlive_grace() -> None:
    body = read(stream_of(*[b"a" * 10] * 8, delay=0.05), grace=0.2, min_rate=50)
    assert len(body) == 80


def test_read_body_has_absolute_deadline() -> None:
    with pytest.raises(HTTPException) as exc:
        read(stream_of(*[b"a" * 10] * 9, delay=0.02), grace=10, max_seconds=0.05)
    assert exc.value.status_code == 408


# --- Yuva sayacı ----------------------------------------------------------------------------------


def test_slot_counter_counts_and_releases() -> None:
    slots = SlotCounter()
    with slots.hold("a"), slots.hold("a"), slots.hold("b"):
        assert slots.total() == 3 and slots.of("a") == 2 and slots.of("c") == 0
    assert slots.total() == 0 and slots.of("a") == 0


def test_slot_counter_releases_after_error() -> None:
    slots = SlotCounter()
    with pytest.raises(ValueError, match="hata"), slots.hold("a"):
        raise ValueError("hata")
    assert slots.total() == 0


# --- Alt süreç yuvası -----------------------------------------------------------------------------


def test_copy_is_refused_while_all_process_slots_are_busy(tmp_path: Path,
                                                          settings: Settings) -> None:
    runner = JobRunner(Database(tmp_path / "d.db"), replace(settings, workers=1))
    with runner.process_slots, pytest.raises(NoProcessSlot):  # denetim alt süreci çalışıyor
        runner.make_output("fixed", "job", bad_thesis(), "yok.yaml")
    outcome = runner.make_output("fixed", "job", b"zip degil", "yok.yaml")
    assert outcome["docx"] is None  # yuva boşalınca çalışır, geçersiz girdiyi reddeder


def test_output_returns_503_when_no_process_slot(settings: Settings,
                                                 mailer: ConsoleMailer) -> None:
    with TestClient(create_app(settings, mailer)) as client:
        csrf = login(client, mailer)
        data = bad_thesis()
        job_id = upload(client, csrf, data)
        assert wait_done(client, job_id) == "done"
        runner = client.app.state.runner  # type: ignore[attr-defined]
        with runner.process_slots:
            busy = output(client, csrf, job_id, "fixed", data)
        assert busy.status_code == 503 and "yoğun" in busy.json()["error"]
        assert output(client, csrf, job_id, "fixed", data).status_code == 200


# --- Kuyruk bayt bütçesi --------------------------------------------------------------------------


def test_held_bytes_cover_queue_and_running_job(tmp_path: Path, settings: Settings) -> None:
    runner = JobRunner(Database(tmp_path / "d.db"), replace(settings, workers=1))
    entered, release = threading.Event(), threading.Event()

    def blocking(*_args: object) -> None:
        entered.set()
        release.wait(10)

    runner.run_now = blocking  # type: ignore[method-assign]
    runner.start()
    try:
        runner.submit("job-1", b"x" * 100, "yok.yaml")
        assert entered.wait(10)
        runner.submit("job-2", b"x" * 50, "yok.yaml")
        assert runner.held_bytes() == 150  # çalışan işin baytları da bellekte
        release.set()
        deadline = time.monotonic() + 10
        while runner.held_bytes() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runner.held_bytes() == 0
    finally:
        release.set()
        runner.stop()


def test_queue_budget_rejects_upload(settings: Settings, mailer: ConsoleMailer) -> None:
    data = bad_thesis()
    limited = replace(settings, max_queued_bytes=len(data) - 1)
    with TestClient(create_app(limited, mailer)) as client:
        csrf = login(client, mailer)
        res = client.post("/jobs", content=data, headers={
            "X-CSRF-Token": csrf, "X-Ruleset": "example",
            "Content-Type": "application/octet-stream"})
        assert res.status_code == 503 and "yoğun" in res.json()["error"]


def test_slow_upload_endpoint_answers_408(settings: Settings, mailer: ConsoleMailer) -> None:
    impatient = replace(settings, upload_grace_seconds=0, upload_max_seconds=0)
    with TestClient(create_app(impatient, mailer)) as client:
        csrf = login(client, mailer)
        res = client.post("/jobs", content=bad_thesis(), headers={
            "X-CSRF-Token": csrf, "X-Ruleset": "example",
            "Content-Type": "application/octet-stream"})
        assert res.status_code == 408 and "uzun sürdü" in res.json()["error"]


# --- Toplam bellek --------------------------------------------------------------------------------


def test_memory_budget_fits_container_limit() -> None:
    s = Settings()
    held = s.max_queued_bytes + 2 * s.max_uploads_in_flight * s.max_upload_bytes
    copies = 2 * s.workers * s.max_upload_bytes
    children = s.workers * MEMORY_LIMIT_BYTES + 300 * 1024**2  # temel süreç
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    limit = re.search(r"mem_limit:\s*(\d+)g", compose)
    assert limit
    assert held + copies + children < int(limit.group(1)) * 1024**3
