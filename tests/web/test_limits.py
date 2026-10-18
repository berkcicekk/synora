"""Kaynak sınırları (ONERILER Ö6): kopya üretimi eşzamanlı iş sınırına tabi, sunucu genelinde
aynı anda en fazla `workers` kopya üretilir, iş kuyruğu sınırlıdır."""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any

from fastapi.testclient import TestClient
from test_web import bad_thesis, login, output, upload, wait_done

from synora.web.app import create_app
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings


def test_output_rejected_while_server_slots_are_busy(settings: Settings,
                                                     mailer: ConsoleMailer) -> None:
    s = replace(settings, workers=1, max_active_jobs=10)
    with TestClient(create_app(s, mailer)) as client:
        csrf = login(client, mailer)
        data = bad_thesis()
        job_id = upload(client, csrf, data)
        wait_done(client, job_id)
        runner = client.app.state.runner  # type: ignore[attr-defined]
        entered, release = threading.Event(), threading.Event()
        real = runner.make_output

        def slow(*args: Any, **kw: Any) -> Any:
            entered.set()
            release.wait(10)
            return real(*args, **kw)

        runner.make_output = slow
        first: dict[str, int] = {}
        t = threading.Thread(target=lambda: first.update(
            code=output(client, csrf, job_id, "fixed", data).status_code))
        t.start()
        assert entered.wait(10)
        busy = output(client, csrf, job_id, "annotated", data)
        release.set()
        t.join(20)
        assert first["code"] == 200
        assert busy.status_code == 503
        assert "yoğun" in busy.json()["error"]
        # Kopya bitince yer açılır.
        assert output(client, csrf, job_id, "annotated", data).status_code == 200


def test_full_queue_rejects_new_jobs(settings: Settings, mailer: ConsoleMailer) -> None:
    with TestClient(create_app(replace(settings, max_queued_jobs=0), mailer)) as client:
        csrf = login(client, mailer)
        res = client.post("/jobs", content=bad_thesis(), headers={
            "X-CSRF-Token": csrf, "X-Ruleset": "example",
            "Content-Type": "application/octet-stream"})
        assert res.status_code == 503
        assert "yoğun" in res.json()["error"]
        assert client.app.state.db.recent_jobs("ogrenci@beun.edu.tr") == []  # type: ignore[attr-defined]
