"""A10 — İş yürütücü.

- Tez dosyası yalnızca bellekte yaşar: kuyruktan alt sürece boru (pipe) ile geçer, diske yazılmaz.
- Her iş ayrı bir süreçte, süre sınırıyla çalışır; sınır aşılırsa süreç sonlandırılır.
  POSIX'te ayrıca bellek ve CPU sınırı uygulanır.
- Saklama süresi dolan işler düzenli olarak silinir.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import sys
import threading
from multiprocessing.connection import Connection

from synora.log import log_event
from synora.web.db import Database
from synora.web.pipeline import PipelineResult, run_pipeline
from synora.web.settings import Settings

MEMORY_LIMIT_BYTES = 2 * 1024 * 1024 * 1024


def _child(conn: Connection, ruleset_path: str, job_id: str, cpu_seconds: int) -> None:
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    data = conn.recv_bytes()
    conn.send(run_pipeline(data, ruleset_path, job_id))
    conn.close()


def run_isolated(data: bytes, ruleset_path: str, job_id: str, timeout: float) -> PipelineResult:
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_child, args=(child, ruleset_path, job_id, int(timeout) + 5),
                       daemon=True)
    proc.start()
    child.close()
    try:
        parent.send_bytes(data)
        if parent.poll(timeout):
            result: PipelineResult = parent.recv()
            return result
        log_event("job.timeout", job_id=job_id, code="TIMEOUT")
        return {"report": None, "error_code": "TIMEOUT"}
    except (EOFError, OSError):
        # Süreç çöktü ya da bellek sınırına takıldı.
        return {"report": None, "error_code": "INTERNAL"}
    finally:
        parent.close()
        proc.join(1)
        if proc.is_alive():
            proc.terminate()
            proc.join(1)


class JobRunner:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._queue: queue.Queue[tuple[str, bytes, str] | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    def start(self) -> None:
        for i in range(self.settings.workers):
            t = threading.Thread(target=self._loop, name=f"synora-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        janitor = threading.Thread(target=self._janitor, name="synora-janitor", daemon=True)
        janitor.start()
        self._threads.append(janitor)

    def stop(self) -> None:
        self._stop.set()
        for _ in range(self.settings.workers):
            self._queue.put(None)

    def submit(self, job_id: str, data: bytes, ruleset_path: str) -> None:
        self._queue.put((job_id, data, ruleset_path))

    def run_now(self, job_id: str, data: bytes, ruleset_path: str) -> None:
        self.db.set_running(job_id)
        if self.settings.isolate_jobs:
            result = run_isolated(data, ruleset_path, job_id, self.settings.job_timeout_seconds)
        else:
            result = run_pipeline(data, ruleset_path, job_id)
        if self.db.get_job(job_id) is not None:  # kullanıcı bu arada silmiş olabilir
            self.db.finish_job(job_id, report=result["report"], error_code=result["error_code"])

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                return
            job_id, data, ruleset_path = item
            try:
                self.run_now(job_id, data, ruleset_path)
            finally:
                del data, item  # tez baytlarına referans kalmasın

    def _janitor(self) -> None:
        while not self._stop.wait(600):
            removed = self.db.purge(self.settings.retention_hours * 3600)
            if removed:
                log_event("retention.purged", count=removed)
