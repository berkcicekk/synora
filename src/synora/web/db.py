"""SQLite deposu: giriş bağlantıları, oturumlar, kullanıcı onayları, işler.

Tez dosyası ASLA buraya yazılmaz (bellekte işlenir). Burada yalnızca e-posta, zaman
damgaları ve metin içermeyen rapor (başlık yolu dahil) bulunur; saklama süresi dolunca silinir.
Gizli değerler (giriş bağlantısı, oturum kimliği) yalnızca SHA-256 özetiyle saklanır.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
-- Günlük iş sınırı sayacı: iş/rapor silinse de düşmez (ONERILER Ö5). E-posta yerine özeti.
CREATE TABLE IF NOT EXISTS job_starts (
    email_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS job_starts_email ON job_starts(email_hash, created_at);
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    consent_version TEXT,
    consent_at REAL
);
"""


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


class Rows(list[tuple[Any, ...]]):
    """Kilit içinde okunmuş sorgu sonucu (cursor'un kullanılan arayüzü: fetchone/fetchall).

    Paylaşılan bağlantıda fetchone kilit dışında çalışırsa eşzamanlı iki okuma birbirinin
    sonucunu bozar (ONERILER Ö9).
    """

    def __init__(self, cur: sqlite3.Cursor) -> None:
        super().__init__(cur.fetchall())
        self.rowcount = cur.rowcount

    def fetchone(self) -> Any:  # sqlite3.Cursor.fetchone ile aynı tip: satır ya da None
        return self[0] if self else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self)


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
    source_sha256: str | None = None  # yeniden yüklemede "aynı dosya mı" denetimi için
    user_roles: str | None = None  # JSON {para_id: rol}: öğrencinin kaydettiği rol seçimleri


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
            token_columns = {row[1] for row in
                             self._conn.execute("PRAGMA table_info(login_tokens)")}
            if "consent" not in token_columns:
                self._conn.execute("ALTER TABLE login_tokens ADD COLUMN consent TEXT")
            columns = {row[1] for row in self._conn.execute("PRAGMA table_info(jobs)")}
            if "source_sha256" not in columns:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN source_sha256 TEXT")
            if "user_roles" not in columns:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN user_roles TEXT")
            # Yeniden başlatmada yarıda kalan işler: dosya bellekteydi, artık yok.
            self._conn.execute(
                "UPDATE jobs SET status='failed', error_code='INTERRUPTED', finished_at=? "
                "WHERE status IN ('queued', 'running')", (time.time(),),
            )

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> Rows:
        with self._lock:
            return Rows(self._conn.execute(sql, params))

    # --- Giriş bağlantıları -----------------------------------------------------------

    def add_login_token(self, token_hash: str, email: str, ttl: float,
                        consent: str | None = None) -> None:
        """consent: kayıtta onaylanan aydınlatma metni sürümü; bağlantı açılınca kaydedilir."""
        now = time.time()
        self.execute("INSERT INTO login_tokens (token_hash, email, created_at, expires_at, used, "
                     "consent) VALUES (?, ?, ?, ?, 0, ?)",
                     (token_hash, email, now, now + ttl, consent))

    def login_requests_since(self, email: str, since: float) -> int:
        row = self.execute("SELECT COUNT(*) FROM login_tokens WHERE email=? AND created_at>=?",
                           (email, since)).fetchone()
        return int(row[0])

    def login_token_consent(self, token_hash: str) -> str | None:
        """Kayıt bağlantısıysa onaylanacak aydınlatma metni sürümü."""
        row = self.execute("SELECT consent FROM login_tokens WHERE token_hash=?",
                           (token_hash,)).fetchone()
        return None if row is None or row[0] is None else str(row[0])

    def consume_login_token(self, token_hash: str, consent_confirmed: bool = False) -> str | None:
        """Bağlantıyı tek seferlik kullanır; geçerliyse e-postayı döndürür.

        Onay yalnızca kayıt bağlantısında ve adres sahibi onay sayfasında kutuyu işaretlediyse
        yazılır (kayıt formunu başkası doldurmuş olabilir).
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT email, expires_at, used, consent FROM login_tokens WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
            now = time.time()
            if row is None or row[2] or row[1] < now:
                return None
            self._conn.execute("UPDATE login_tokens SET used=1 WHERE token_hash=?", (token_hash,))
            # Düz girişte kullanıcı satırı açılmaz (e-posta kalıcı olarak tutulmaz).
            if row[3] and consent_confirmed:
                self._conn.execute(
                    "INSERT INTO users (email, created_at, consent_version, consent_at) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(email) DO UPDATE SET "
                    "consent_version=excluded.consent_version, consent_at=excluded.consent_at",
                    (row[0], now, row[3], now))
            return str(row[0])

    def delete_login_token(self, token_hash: str) -> None:
        self.execute("DELETE FROM login_tokens WHERE token_hash=?", (token_hash,))

    def login_token_valid(self, token_hash: str) -> bool:
        row = self.execute("SELECT expires_at, used FROM login_tokens WHERE token_hash=?",
                           (token_hash,)).fetchone()
        return row is not None and not row[1] and row[0] >= time.time()

    def register_user(self, email: str, consent_version: str) -> None:
        """Doğrulamasız kayıt (demo kipi): kullanıcı satırı (whitelist) ve onay kaydı.

        Adres sahipliği doğrulanmadığı için onay, formu gönderenin beyanıdır.
        """
        now = time.time()
        self.execute(
            "INSERT INTO users (email, created_at, consent_version, consent_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(email) DO UPDATE SET "
            "consent_version=excluded.consent_version, consent_at=excluded.consent_at",
            (email, now, consent_version, now))

    def user_count(self) -> int:
        """Kayıtlı kullanıcı sayısı (tanıtım sayfasındaki sayılar şeridi için)."""
        return int(self.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def user_consent(self, email: str) -> tuple[str, float] | None:
        """Kullanıcının onayladığı aydınlatma metni sürümü ve zamanı; onay yoksa None."""
        row = self.execute("SELECT consent_version, consent_at FROM users WHERE email=?",
                           (email,)).fetchone()
        if row is None or row[0] is None:
            return None
        return str(row[0]), float(row[1])

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
        now = time.time()
        with self._lock:
            self._conn.execute("INSERT INTO jobs (id, email, ruleset, status, created_at) "
                               "VALUES (?, ?, ?, 'queued', ?)", (job_id, email, ruleset, now))
            self._conn.execute("INSERT INTO job_starts VALUES (?, ?)", (_email_hash(email), now))

    def set_running(self, job_id: str) -> None:
        self.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))

    def requeue(self, job_id: str) -> None:
        """Aynı dosyayla yeniden denetim: rapor yeni sonuç gelene kadar korunur."""
        self.execute("UPDATE jobs SET status='queued' WHERE id=?", (job_id,))

    def set_user_roles(self, job_id: str, roles: str | None) -> None:
        self.execute("UPDATE jobs SET user_roles=? WHERE id=?", (roles, job_id))

    def finish_job(self, job_id: str, *, report: str | None, error_code: str | None,
                   source_sha256: str | None = None) -> None:
        status = "done" if report is not None else "failed"
        self.execute("UPDATE jobs SET status=?, report=?, error_code=?, finished_at=?, "
                     "source_sha256=? WHERE id=?",
                     (status, report, error_code, time.time(), source_sha256, job_id))

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
        row = self.execute("SELECT COUNT(*) FROM job_starts WHERE email_hash=? AND created_at>=?",
                           (_email_hash(email), since)).fetchone()
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
            self._conn.execute("DELETE FROM job_starts WHERE created_at < ?", (now - 86400,))
            # Silinen raporlar WAL dosyasında kalmasın: ana dosyaya işle (secure_delete sıfırlar)
            # ve WAL'ı boşalt.
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return cur.rowcount
