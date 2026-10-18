"""A9 veritabanı: paylaşılan sqlite3 bağlantısında eşzamanlı okuma (ONERILER Ö9).

`Database.execute` eskiden kilidi yalnızca `execute` sırasında tutuyordu; `fetchone()` kilit
dışında, paylaşılan bağlantı üzerinde çalışıyordu. İş yürütücü ile istek iş parçacığı aynı SQL'i
aynı anda çalıştırınca biri ötekinin sonucunu bozuyordu: var olan iş için None, InterfaceError.
Sonuç: iş sonsuza dek "denetleniyor", öğrenci kendi raporunda ara sıra 404. Artık satırlar kilit
içinde okunur.
"""

from __future__ import annotations

import threading
from pathlib import Path

from synora.web.db import Database


def test_concurrent_reads_return_the_right_job(tmp_path: Path) -> None:
    db = Database(tmp_path / "t.db")
    ids = [f"is-{i:020d}" for i in range(2)]
    for i, job_id in enumerate(ids):
        db.add_job(job_id, f"u{i}@beun.edu.tr", "example")
    wrong: list[str] = []

    def reader(i: int) -> None:
        for _ in range(3000):
            try:
                job = db.get_job(ids[i])
            except Exception as exc:  # yarışın belirtisi (InterfaceError vb.)
                wrong.append(type(exc).__name__)
                continue
            if job is None or job.id != ids[i] or job.email != f"u{i}@beun.edu.tr":
                wrong.append("yanlış satır")

    threads = [threading.Thread(target=reader, args=(n % 2,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert wrong == []
