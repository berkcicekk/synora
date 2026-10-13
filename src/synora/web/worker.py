"""A10 — İş yürütücü.

- Tez dosyası yalnızca bellekte yaşar: kuyruktan alt sürece boru (pipe) ile geçer, diske yazılmaz.
- Her iş ayrı bir süreçte, süre sınırıyla çalışır; sınır aşılırsa süreç sonlandırılır.
  POSIX'te ayrıca bellek ve CPU sınırı uygulanır.
- Saklama süresi dolan işler düzenli olarak silinir.
"""

from __future__ import annotations

import contextlib
import multiprocessing as mp
import queue
import sys
import threading
from multiprocessing.connection import Connection

from synora.log import log_event
from synora.web.db import Database
from synora.web.pipeline import (
    OutputKind,
    OutputResult,
    PipelineResult,
    run_output,
    run_pipeline,
)
from synora.web.settings import Settings

MEMORY_LIMIT_BYTES = 2 * 1024 * 1024 * 1024


UserRoles = dict[str, str] | None


def _child(
    conn: Connection, task: str, ruleset_path: str, job_id: str, cpu_seconds: int,
    user_roles: UserRoles = None,
) -> None:
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    data = conn.recv_bytes()
    if task == "check":
        conn.send(run_pipeline(data, ruleset_path, job_id, user_roles))
    elif task in ("fixed", "annotated"):
        conn.send(run_output(task, data, ruleset_path, job_id,  # type: ignore[arg-type]
                             user_roles))
    conn.close()


def _spawn(task: str, data: bytes, ruleset_path: str, job_id: str, timeout: float,
           user_roles: UserRoles = None) -> object:
    """Görevi ayrı süreçte çalıştırır; süre aşımında süreci sonlandırır.
    Başarısızlıkta hata kodu (str) döner."""
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_child,
                       args=(child, task, ruleset_path, job_id, int(timeout) + 5, user_roles),
                       daemon=True)
    proc.start()
    child.close()
    try:
        parent.send_bytes(data)
        if parent.poll(timeout):
            return parent.recv()
        log_event("job.timeout", job_id=job_id, code="TIMEOUT")
        return "TIMEOUT"
    except (EOFError, OSError):
        # Süreç çöktü ya da bellek sınırına takıldı.
        return "INTERNAL"
    finally:
        parent.close()
        proc.join(1)
        if proc.is_alive():
            proc.terminate()
            proc.join(1)


def run_isolated(data: bytes, ruleset_path: str, job_id: str, timeout: float,
                 user_roles: UserRoles = None) -> PipelineResult:
    result = _spawn("check", data, ruleset_path, job_id, timeout, user_roles)
    if isinstance(result, str):
        return {"report": None, "error_code": result, "source_sha256": None}
    return result  # type: ignore[return-value]


def output_isolated(
    kind: OutputKind, data: bytes, ruleset_path: str, job_id: str, timeout: float,
    user_roles: UserRoles = None,
) -> OutputResult:
    result = _spawn(kind, data, ruleset_path, job_id, timeout, user_roles)
    if isinstance(result, str):
        return {"docx": None, "error_code": result}
    return result  # type: ignore[return-value]


class JobRunner:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._queue: queue.Queue[tuple[str, bytes, str, UserRoles] | None] = queue.Queue()
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

    def submit(self, job_id: str, data: bytes, ruleset_path: str,
               user_roles: UserRoles = None) -> None:
        self._queue.put((job_id, data, ruleset_path, user_roles))

    def run_now(self, job_id: str, data: bytes, ruleset_path: str,
                user_roles: UserRoles = None) -> None:
        self.db.set_running(job_id)
        if self.settings.isolate_jobs:
            result = run_isolated(data, ruleset_path, job_id, self.settings.job_timeout_seconds,
                                  user_roles)
        else:
            result = run_pipeline(data, ruleset_path, job_id, user_roles)
        if self.db.get_job(job_id) is not None:  # kullanıcı bu arada silmiş olabilir
            self.db.finish_job(job_id, report=result["report"], error_code=result["error_code"],
                               source_sha256=result["source_sha256"])

    def make_output(
        self, kind: OutputKind, job_id: str, data: bytes, ruleset_path: str,
        user_roles: UserRoles = None,
    ) -> OutputResult:
        """Düzeltilmiş/yorumlu kopyayı istek içinde üretir; sonuç saklanmaz."""
        if self.settings.isolate_jobs:
            return output_isolated(kind, data, ruleset_path, job_id,
                                   self.settings.job_timeout_seconds, user_roles)
        return run_output(kind, data, ruleset_path, job_id, user_roles)

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                return
            job_id, data, ruleset_path, user_roles = item
            try:
                self.run_now(job_id, data, ruleset_path, user_roles)
            except Exception:
                # Bir işteki beklenmeyen hata (ör. geçici veritabanı kilidi) yürütücüyü öldürmemeli;
                # yoksa sonraki tüm işler sonsuza dek "sırada" kalır.
                log_event("job.worker_error", job_id=job_id, code="INTERNAL")
                with contextlib.suppress(Exception):
                    self.db.finish_job(job_id, report=None, error_code="INTERNAL")
            finally:
                del data, item  # tez baytlarına referans kalmasın

    def _janitor(self) -> None:
        while not self._stop.wait(600):
            removed = self.db.purge(self.settings.retention_hours * 3600)
            if removed:
                log_event("retention.purged", count=removed)
