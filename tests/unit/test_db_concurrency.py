"""A9 veritabanı: paylaşılan sqlite3 bağlantısında eşzamanlı okuma (gece taraması).

`Database.execute` kilidi yalnızca `execute` sırasında tutuyor; `fetchone()` kilit dışında,
paylaşılan bağlantı üzerinde çalışıyor. İş yürütücü ile istek iş parçacığı aynı SQL'i aynı anda
çalıştırınca sqlite3'ün deyim önbelleği aynı hazır deyimi paylaşıyor ve biri ötekinin sonucunu
bozuyor: var olan iş için None, InterfaceError. Sonuç: iş yürütücü işi "silinmiş" sanıp sonucu
yazmıyor → iş sonsuza dek "denetleniyor"; öğrenci kendi raporunda ara sıra 404 görüyor.

Not: tests/web/conftest.py bu yarışı test ortamında kapatan bir ara katman kullanır (web testleri
rastgele kırmızıya dönmesin diye); bu dosya ara katmansız gerçek davranışı sınar.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from synora.web.db import Database


@pytest.mark.xfail(strict=False, reason=(
    "Yarış: fetchone kilit dışında. Yeniden üretim: 4 iş parçacığı × 3000 okuma → ~50 yanlış "
    "sonuç. Olasılıksal olduğu için strict değil. Öneri: ONERILER Ö9 (ÖNCELİKLİ)."))
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
