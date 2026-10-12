"""Tek bir tezin denetimi: bayt → rapor JSON. İş yürütücü bunu ayrı bir süreçte çalıştırır.

Dönüş yalnızca rapor (metin içermez; başlık yolları dahil) ya da hata kodudur.
"""

from __future__ import annotations

import json
import time
from typing import TypedDict

from synora.check import check
from synora.errors import SynoraError
from synora.ingest import open_docx
from synora.locate import locations
from synora.log import log_event
from synora.parse import parse_package
from synora.report import to_json
from synora.ruleset import load_ruleset


class PipelineResult(TypedDict):
    report: str | None
    error_code: str | None


def run_pipeline(data: bytes, ruleset_path: str, job_id: str = "job") -> PipelineResult:
    started = time.monotonic()
    try:
        rules = load_ruleset(ruleset_path)
        pkg = open_docx(data)
        doc = parse_package(pkg)
        result = check(doc, rules)
        report = json.loads(to_json(result, rules))
        where = locations(doc, result.roles)
        for f in report["findings"]:
            f["location"] = where.get(f["para_id"]) if f["para_id"] else None
        report["fingerprint"] = None  # F5'te düzeltilmiş dosya ile birlikte doldurulacak
    except SynoraError as exc:
        log_event("job.rejected", job_id=job_id, code=exc.code.value)
        return {"report": None, "error_code": exc.code.value}
    except Exception:
        # Ayrıntı (ve olası belge parçaları) log'a yazılmaz; yalnızca tür.
        log_event("job.crashed", job_id=job_id, code="INTERNAL")
        return {"report": None, "error_code": "INTERNAL"}
    log_event("job.done", job_id=job_id,
              duration_ms=int((time.monotonic() - started) * 1000),
              count=len(report["findings"]))
    return {"report": json.dumps(report, ensure_ascii=False), "error_code": None}
