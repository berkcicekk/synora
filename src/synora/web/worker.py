"""A10 — İş yürütücü.

- Tez dosyası yalnızca bellekte yaşar: kuyruktan alt sürece boru (pipe) ile geçer, diske yazılmaz.
- Her iş ayrı bir süreçte, süre sınırıyla çalışır; sınır aşılırsa süreç sonlandırılır.
  POSIX'te ayrıca bellek ve CPU sınırı uygulanır.
- Saklama süresi dolan işler düzenli olarak silinir.
"""

from __future__ import annotations

import contextlib
import json
import multiprocessing as mp
import os
import queue
import re
import sys
import threading
import time
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
SETTINGS_ENV_PREFIX = "SYNORA_"
MAX_CHILD_MESSAGE_BYTES = 700 * 1024 * 1024  # açılmış paket tavanı (600 MB) + pay
# Süre dolduktan sonra yarım kalan iletinin okunması için tanınan pay; sonra süreç öldürülür.
CHILD_KILL_GRACE_SECONDS = 30.0
CHILD_MAX_OPEN_FILES = 256


UserRoles = dict[str, str] | None


class NoProcessSlot(Exception):
    """Tüm alt süreç yuvaları dolu; kopya üretimi şimdi başlatılamaz."""


# Alt süreç güvenilmez dosya işler; ele geçirilirse üst süreçte kod çalıştıramasın diye sonucu
# pickle değil, burada doğrulanan JSON ya da ham bayt olarak gönderir.
_OUTPUT_DOCX = b"D"
_OUTPUT_ERROR = b"E"
_ERROR_CODE_RE = re.compile(rb"[A-Z0-9_]{1,64}")


def _pipeline_failure(error_code: str) -> PipelineResult:
    return {"report": None, "stats": None, "error_code": error_code, "source_sha256": None,
            "training": []}


def encode_pipeline(result: PipelineResult) -> bytes:
    return json.dumps(result).encode()


def decode_pipeline(message: bytes) -> PipelineResult:
    try:
        raw = json.loads(message)
        report, stats, code, sha = (raw["report"], raw["stats"], raw["error_code"],
                                    raw["source_sha256"])
        training = [(str(f), str(label), str(rs)) for f, label, rs in raw["training"]]
    except (ValueError, KeyError, TypeError):
        return _pipeline_failure("INTERNAL")
    if not (all(v is None or isinstance(v, str) for v in (report, stats, code, sha))
            and (report is not None or code is not None)):
        return _pipeline_failure("INTERNAL")
    return {"report": report, "stats": stats, "error_code": code, "source_sha256": sha,
            "training": training}


def encode_output(result: OutputResult) -> bytes:
    if result["docx"] is not None:
        return _OUTPUT_DOCX + result["docx"]
    return _OUTPUT_ERROR + (result["error_code"] or "INTERNAL").encode()


def decode_output(message: bytes) -> OutputResult:
    kind, body = message[:1], message[1:]
    if kind == _OUTPUT_DOCX:
        return {"docx": body, "error_code": None}
    if kind == _OUTPUT_ERROR and _ERROR_CODE_RE.fullmatch(body):
        return {"docx": None, "error_code": body.decode()}
    return {"docx": None, "error_code": "INTERNAL"}


def scrub_environment() -> None:
    """Alt süreç güvenilmez dosya işler: SMTP parolası gibi ayarlar ortamında kalmasın."""
    for name in [n for n in os.environ if n.startswith(SETTINGS_ENV_PREFIX)]:
        del os.environ[name]


def _make_undumpable() -> None:
    """PR_SET_DUMPABLE=0 (Linux): döküm olmaz, aynı kullanıcı /proc'tan belleği okuyamaz."""
    import ctypes

    with contextlib.suppress(OSError, AttributeError):
        ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)


def _apply_child_limits(cpu_seconds: int) -> None:
    """Güvenilmez dosyayı işleyen sürecin sınırları: tez baytları döküm ya da dosyayla diske
    düşmesin (süreç hiçbir dosyaya yazmaz; sonuç boru hattından döner)."""
    if sys.platform == "win32":
        return
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (CHILD_MAX_OPEN_FILES, CHILD_MAX_OPEN_FILES))
    _make_undumpable()


def _child(
    conn: Connection, task: str, ruleset_path: str, job_id: str, cpu_seconds: int,
    user_roles: UserRoles = None,
) -> None:
    scrub_environment()
    _apply_child_limits(cpu_seconds)
    data = conn.recv_bytes()
    if task == "check":
        conn.send_bytes(encode_pipeline(run_pipeline(data, ruleset_path, job_id, user_roles)))
    elif task in ("fixed", "annotated"):
        conn.send_bytes(encode_output(run_output(task, data, ruleset_path,  # type: ignore[arg-type]
                                                 job_id, user_roles)))
    conn.close()


def _spawn(task: str, data: bytes, ruleset_path: str, job_id: str, timeout: float,
           user_roles: UserRoles = None) -> bytes | str:
    """Görevi ayrı süreçte çalıştırır; süre aşımında süreci sonlandırır. Sonuç ham ileti (bayt),
    başarısızlıkta hata kodudur (str)."""
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_child,
                       args=(child, task, ruleset_path, job_id, int(timeout) + 5, user_roles),
                       daemon=True)
    proc.start()
    child.close()
    # Dolu boru ya da yarım ileti yazma/okumayı süresiz tutmasın: süre dolunca süreç ölür.
    watchdog = threading.Timer(timeout + CHILD_KILL_GRACE_SECONDS, proc.kill)
    watchdog.daemon = True
    watchdog.start()
    try:
        parent.send_bytes(data)
        if parent.poll(timeout):
            return parent.recv_bytes(MAX_CHILD_MESSAGE_BYTES)
        log_event("job.timeout", job_id=job_id, code="TIMEOUT")
        return "TIMEOUT"
    except (EOFError, OSError):
        # Süreç çöktü ya da bellek sınırına takıldı.
        return "INTERNAL"
    finally:
        watchdog.cancel()
        parent.close()
        proc.join(1)
        if proc.is_alive():
            proc.terminate()
            proc.join(1)
        if proc.is_alive():
            proc.kill()
            proc.join(1)


def run_isolated(data: bytes, ruleset_path: str, job_id: str, timeout: float,
                 user_roles: UserRoles = None) -> PipelineResult:
    result = _spawn("check", data, ruleset_path, job_id, timeout, user_roles)
    return _pipeline_failure(result) if isinstance(result, str) else decode_pipeline(result)


def output_isolated(
    kind: OutputKind, data: bytes, ruleset_path: str, job_id: str, timeout: float,
    user_roles: UserRoles = None,
) -> OutputResult:
    result = _spawn(kind, data, ruleset_path, job_id, timeout, user_roles)
    if isinstance(result, str):
        return {"docx": None, "error_code": result}
    return decode_output(result)


class JobRunner:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._queue: queue.Queue[tuple[str, bytes, str, UserRoles] | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        # Denetim ve kopya alt süreçleri toplamı; her biri MEMORY_LIMIT_BYTES'a kadar bellek alır.
        self.process_slots = threading.BoundedSemaphore(settings.workers)
        self._held_bytes = 0
        self._held_lock = threading.Lock()

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

    def alive(self) -> bool:
        return all(t.is_alive() for t in self._threads)

    def queued(self) -> int:
        return self._queue.qsize()

    def held_bytes(self) -> int:
        """Kuyruktaki ve çalışan işlerin bellekte tuttuğu dosya baytları."""
        with self._held_lock:
            return self._held_bytes

    def _add_held_bytes(self, delta: int) -> None:
        with self._held_lock:
            self._held_bytes += delta

    def submit(self, job_id: str, data: bytes, ruleset_path: str,
               user_roles: UserRoles = None) -> None:
        self._add_held_bytes(len(data))
        self._queue.put((job_id, data, ruleset_path, user_roles))

    def run_now(self, job_id: str, data: bytes, ruleset_path: str,
                user_roles: UserRoles = None) -> None:
        self.db.set_running(job_id)
        started = time.monotonic()
        with self.process_slots:
            if self.settings.isolate_jobs:
                result = run_isolated(data, ruleset_path, job_id,
                                      self.settings.job_timeout_seconds, user_roles)
            else:
                result = run_pipeline(data, ruleset_path, job_id, user_roles)
        # Kullanıcı bu arada silmişse UPDATE hiçbir satıra dokunmaz.
        self.db.finish_job(job_id, report=result["report"], error_code=result["error_code"],
                           source_sha256=result["source_sha256"], stats=result["stats"],
                           seconds=time.monotonic() - started)
        job = self.db.get_job_meta(job_id)
        if job is None:  # öğrenci bu arada sildi
            return
        if result["training"] and job.collect:
            # F6: yalnızca açık rıza işaretli işlerde; satırlar metinsiz ve iş kimliksizdir.
            self.db.add_training(result["training"][:self.settings.training_rows_per_job])
        if result["stats"]:
            # Anonim bulgu sayacı ("en sık yapılan hatalar"); kimlik ya da metin yok.
            rule_counts = json.loads(result["stats"])["rule_counts"]
            if rule_counts:
                self.db.add_finding_counts(job.ruleset, rule_counts)

    def make_output(
        self, kind: OutputKind, job_id: str, data: bytes, ruleset_path: str,
        user_roles: UserRoles = None,
    ) -> OutputResult:
        """Düzeltilmiş/yorumlu kopyayı istek içinde üretir; sonuç saklanmaz. Yuva yoksa beklemez,
        NoProcessSlot fırlatır: öğrenci kuyruk arkasında yanıtsız kalmasın."""
        if not self.process_slots.acquire(blocking=False):
            raise NoProcessSlot
        try:
            if self.settings.isolate_jobs:
                return output_isolated(kind, data, ruleset_path, job_id,
                                       self.settings.job_timeout_seconds, user_roles)
            return run_output(kind, data, ruleset_path, job_id, user_roles)
        finally:
            self.process_slots.release()

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                return
            job_id, data, ruleset_path, user_roles = item
            size = len(data)
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
                self._add_held_bytes(-size)

    def _janitor(self) -> None:
        while not self._stop.wait(600):
            try:
                removed = self.db.purge(self.settings.retention_hours * 3600)
                self.db.trim_training(self.settings.training_keep_rows,
                                      self.settings.training_keep_days)
            except Exception:
                # Geçici hata (kilit, dolu disk) temizliği kalıcı durdurmasın: raporlar
                # süresinde silinmeli. Bir sonraki turda yeniden denenir.
                log_event("retention.purge_failed", code="INTERNAL")
                continue
            if removed:
                log_event("retention.purged", count=removed)
