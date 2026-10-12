"""content_fingerprint: belgenin metin içeriğinin özeti.

Synora'nın değişmez kuralı: her yazma işleminden sonra fingerprint girdiyle aynı olmalı.
Biçim (stil, punto, kenar boşluğu, run bölünmesi) özeti etkilemez; görünen tek bir
karakterin değişmesi, eklenmesi ya da silinmesi, paragraf eklenmesi/silinmesi etkiler.

Kapsam: gövde, dipnotlar, sonnotlar, üstbilgiler, altbilgiler; metin kutuları ve
alan sonuçları dahil (bkz. synora.text). Alan komutları ve silinmiş metin hariç.
Paragraflar part içindeki tüm w:p öğeleridir; mc:Fallback kopyaları da dahildir
(daha sıkı: yedek kopyadaki bir değişiklik de yakalanır).
"""

from __future__ import annotations

import hashlib

from synora.ingest import DocxPackage
from synora.ooxml import w
from synora.package import parse_part, story_parts
from synora.text import FieldTracker, visible_text

VERSION = b"synora-fingerprint-v1\n"


def content_fingerprint(pkg: DocxPackage) -> str:
    h = hashlib.sha256(VERSION)
    for story, part in story_parts(pkg):
        h.update(f"\x1d{story.value}:{part}\n".encode())
        tracker = FieldTracker()
        for index, p in enumerate(parse_part(pkg, part).iter(w("p"))):
            h.update(f"{index}\x1f".encode())
            h.update(visible_text(p, tracker).encode("utf-8", "surrogatepass"))
            h.update(b"\x1e")
    return h.hexdigest()
