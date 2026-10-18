"""synora serve: üretimde erişim kaydı kapalı (giriş bağlantısı sızmaz), uygulama kayıtları açık."""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest
from typer.testing import CliRunner

from synora import log
from synora.cli import app

runner = CliRunner()


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    import uvicorn

    import synora.web.app as web_app

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app_, **kw: calls.append(kw))
    monkeypatch.setattr(web_app, "create_app", lambda: object())
    monkeypatch.setattr(log, "configure_logging", lambda stream=None: None)
    return calls


def test_production_disables_access_log(uvicorn_calls: list[dict[str, Any]]) -> None:
    # uvicorn erişim kaydı sorgu dizesini yazar: /auth?token=… 15 dakika boyunca giriş demektir.
    assert runner.invoke(app, ["serve"]).exit_code == 0
    assert uvicorn_calls[-1]["access_log"] is False


def test_dev_keeps_access_log(uvicorn_calls: list[dict[str, Any]],
                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SYNORA_DEV", raising=False)
    monkeypatch.delenv("SYNORA_BASE_URL", raising=False)
    assert runner.invoke(app, ["serve", "--dev"]).exit_code == 0
    assert uvicorn_calls[-1]["access_log"] is True


def test_configure_logging_emits_synora_events() -> None:
    logger = logging.getLogger(log.LOGGER_NAME)
    saved = (logger.handlers[:], logger.level, logger.propagate)
    stream = io.StringIO()
    try:
        log.configure_logging(stream)
        log.configure_logging(stream)  # ikinci çağrı ikinci bir işleyici eklemez
        log.log_event("job.done", job_id="j1", count=3)
        lines = stream.getvalue().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0].split(" ", 2)[2]) == {"event": "job.done", "job_id": "j1",
                                                          "count": 3}
    finally:
        logger.handlers[:], logger.level, logger.propagate = saved
