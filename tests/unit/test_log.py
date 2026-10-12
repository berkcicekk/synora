import json
import logging

import pytest

from synora.log import LOGGER_NAME, log_event


def test_writes_allowed_fields_as_json(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        log_event("ingest.ok", job_id="job-1", hash="ab12", code="OK")
    record = json.loads(caplog.records[-1].getMessage())
    assert record == {"event": "ingest.ok", "job_id": "job-1", "hash": "ab12", "code": "OK"}


def test_rejects_unknown_field() -> None:
    with pytest.raises(ValueError):
        log_event("x", text="tez cümlesi")


@pytest.mark.parametrize("value", ["iki kelime", "ç", "a" * 200, "x\ny"])
def test_rejects_free_text_values(value: str) -> None:
    with pytest.raises(ValueError):
        log_event("x", para_id=value)


def test_rejects_bad_event_name() -> None:
    with pytest.raises(ValueError):
        log_event("serbest metin olay")


def test_accepts_int_values(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        log_event("check.done", job_id="j", count=12)
    assert json.loads(caplog.records[-1].getMessage())["count"] == 12
