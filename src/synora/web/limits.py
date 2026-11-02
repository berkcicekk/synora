"""İstek başına kaynak sınırları: gövde okuma süresi ve boyutu, eşzamanlı yuva sayımı."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Iterator
from contextlib import contextmanager

from fastapi import HTTPException
from starlette.requests import ClientDisconnect

UPLOAD_TOO_LARGE = "Dosya çok büyük."
UPLOAD_TOO_SLOW = "Yükleme çok uzun sürdü. Bağlantınızı kontrol edip yeniden deneyin."


async def read_body(stream: AsyncIterable[bytes], *, max_bytes: int, grace_seconds: float,
                    min_bytes_per_second: int, max_seconds: float) -> bytes:
    """Gövdeyi belleğe alır; sınırı aşan ya da fazla yavaş gelen yüklemeyi keser.

    Gelen her bayt süre kazandırır, bu yüzden yavaş ama gerçek bir bağlantı yükleyebilir; damla
    damla veri gönderen ya da susan istemci yükleme yuvasını tutamaz.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    final_deadline = started + max_seconds
    chunks: list[bytes] = []
    size = 0
    try:
        async with asyncio.timeout_at(min(started + grace_seconds, final_deadline)) as timer:
            async for chunk in stream:
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, UPLOAD_TOO_LARGE)
                chunks.append(chunk)
                earned = started + grace_seconds + size / min_bytes_per_second
                timer.reschedule(min(earned, final_deadline))
    except TimeoutError:
        raise HTTPException(408, UPLOAD_TOO_SLOW) from None
    except ClientDisconnect:
        raise HTTPException(400, "Bağlantı kesildi.") from None
    return b"".join(chunks)


class SlotCounter:
    """Hesap başına eşzamanlı iş sayacı. Yalnızca olay döngüsünde değişir: denetim ile `hold`
    arasında await olmadığı sürece yarış yoktur."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def total(self) -> int:
        return sum(self._counts.values())

    def of(self, email: str) -> int:
        return self._counts.get(email, 0)

    @contextmanager
    def hold(self, email: str) -> Iterator[None]:
        self._counts[email] = self.of(email) + 1
        try:
            yield
        finally:
            remaining = self._counts[email] - 1
            if remaining:
                self._counts[email] = remaining
            else:
                del self._counts[email]
