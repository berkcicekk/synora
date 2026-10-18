"""Tez metni sızdıramayan yapılandırılmış log.

Yalnızca izinli alan adları kabul edilir ve string değerler boşluksuz, ASCII, kısa
kimliklerle sınırlıdır. Böylece bir cümle ya da paragraf yanlışlıkla log'a giremez.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import TextIO

LOGGER_NAME = "synora"

ALLOWED_FIELDS = frozenset(
    {"job_id", "para_id", "rule_id", "hash", "code", "count", "part", "duration_ms"}
)
_EVENT_RE = re.compile(r"[a-z0-9_.]{1,64}")
_VALUE_RE = re.compile(r"[A-Za-z0-9_.:/\-\[\]]{1,128}")

_logger = logging.getLogger(LOGGER_NAME)


def log_event(event: str, **fields: str | int) -> None:
    if not _EVENT_RE.fullmatch(event):
        raise ValueError("geçersiz olay adı")
    record: dict[str, str | int] = {"event": event}
    for key, value in fields.items():
        if key not in ALLOWED_FIELDS:
            raise ValueError(f"izinsiz log alanı: {key}")
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise ValueError(f"izinsiz değer tipi: {key}")
        if isinstance(value, str) and not _VALUE_RE.fullmatch(value):
            raise ValueError(f"izinsiz değer biçimi: {key}")
        record[key] = value
    _logger.info(json.dumps(record, ensure_ascii=True))


def configure_logging(stream: TextIO | None = None) -> None:
    """Sunucu için: synora olaylarını INFO düzeyinde standart çıktıya yazar (journald toplar).

    Yapılandırılmazsa kayıtlar atılıyordu. Tekrar çağrılınca tek işleyici kalır.
    """
    logger = logging.getLogger(LOGGER_NAME)
    for handler in logger.handlers[:]:
        if getattr(handler, "_synora", False):
            logger.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                           datefmt="%Y-%m-%dT%H:%M:%S%z"))
    handler._synora = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
