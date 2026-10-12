"""SQLite deposu: giriş bağlantıları, oturumlar, işler.

Tez dosyası ASLA buraya yazılmaz (bellekte işlenir). Burada yalnızca e-posta, zaman
damgaları ve metin içermeyen rapor (başlık yolu dahil) bulunur; saklama süresi dolunca silinir.
Gizli değerler (giriş bağlantısı, oturum kimliği) yalnızca SHA-256 özetiyle saklanır.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS login_tokens (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    id_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    csrf TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    ruleset TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    finished_at REAL,
    error_code TEXT,
    report TEXT
);
CREATE INDEX IF NOT EXISTS jobs_email ON jobs(email, created_at);
"""


@dataclass(frozen=True)
class Job:
    id: str
    email: str
    ruleset: str
    status: str  # queued / running / done / failed
    created_at: float
    finished_at: float | None
    error_code: str | None
    report: str | None


class Database:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA secure_delete=ON")
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            # Yeniden başlatmada yarıda kalan işler: dosya bellekteydi, artık yok.
            self._conn.execute(
                "UPDATE jobs SET status='failed', error_code='INTERRUPTED', finished_at=? "
                "WHERE status IN ('queued', 'running')", (time.time(),),
            )

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    # --- Giriş bağlantıları -----------------------------------------------------------

    def add_login_token(self, token_hash: str, email: str, ttl: float) -> None:
        now = time.time()
        self.execute("INSERT INTO login_tokens VALUES (?, ?, ?, ?, 0)",
                     (token_hash, email, now, now + ttl))

    def login_requests_since(self, email: str, since: float) -> int:
        row = self.execute("SELECT COUNT(*) FROM login_tokens WHERE email=? AND created_at>=?",
                           (email, since)).fetchone()
        return int(row[0])

    def consume_login_token(self, token_hash: str) -> str | None:
        """Bağlantıyı tek seferlik kullanır; geçerliyse e-postayı döndürür."""
        with self._lock:
            row = self._conn.execute(
                "SELECT email, expires_at, used FROM login_tokens WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
            if row is None or row[2] or row[1] < time.time():
                return None
            self._conn.execute("UPDATE login_tokens SET used=1 WHERE token_hash=?", (token_hash,))
            return str(row[0])

    def login_token_valid(self, token_hash: str) -> bool:
        row = self.execute("SELECT expires_at, used FROM login_tokens WHERE token_hash=?",
                           (token_hash,)).fetchone()
        return row is not None and not row[1] and row[0] >= time.time()

    # --- Oturumlar ------------------------------------------------------------------------

    def add_session(self, id_hash: str, email: str, csrf: str, ttl: float) -> None:
        self.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                     (id_hash, email, csrf, time.time() + ttl))

    def get_session(self, id_hash: str) -> tuple[str, str] | None:
        row = self.execute("SELECT email, csrf, expires_at FROM sessions WHERE id_hash=?",
                           (id_hash,)).fetchone()
        if row is None or row[2] < time.time():
            return None
        return str(row[0]), str(row[1])

    def delete_session(self, id_hash: str) -> None:
        self.execute("DELETE FROM sessions WHERE id_hash=?", (id_hash,))

    # --- İşler ----------------------------------------------------------------------------

    def add_job(self, job_id: str, email: str, ruleset: str) -> None:
        self.execute("INSERT INTO jobs (id, email, ruleset, status, created_at) "
                     "VALUES (?, ?, ?, 'queued', ?)", (job_id, email, ruleset, time.time()))

    def set_running(self, job_id: str) -> None:
        self.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))

    def finish_job(self, job_id: str, *, report: str | None, error_code: str | None) -> None:
        status = "done" if report is not None else "failed"
        self.execute("UPDATE jobs SET status=?, report=?, error_code=?, finished_at=? WHERE id=?",
                     (status, report, error_code, time.time(), job_id))

    def get_job(self, job_id: str) -> Job | None:
        row = self.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return Job(*row) if row else None

    def recent_jobs(self, email: str, limit: int = 10) -> list[Job]:
        rows = self.execute("SELECT * FROM jobs WHERE email=? ORDER BY created_at DESC LIMIT ?",
                            (email, limit)).fetchall()
        return [Job(*r) for r in rows]

    def active_jobs(self, email: str) -> int:
        row = self.execute("SELECT COUNT(*) FROM jobs WHERE email=? AND status IN "
                           "('queued', 'running')", (email,)).fetchone()
        return int(row[0])

    def jobs_since(self, email: str, since: float) -> int:
        row = self.execute("SELECT COUNT(*) FROM jobs WHERE email=? AND created_at>=?",
                           (email, since)).fetchone()
        return int(row[0])

    def delete_job(self, job_id: str) -> None:
        self.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    # --- Saklama süresi ---------------------------------------------------------------------

    def purge(self, retention_seconds: float) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute("DELETE FROM jobs WHERE created_at < ?",
                                     (now - retention_seconds,))
            self._conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            self._conn.execute("DELETE FROM login_tokens WHERE expires_at < ?", (now - 3600,))
            return cur.rowcount
