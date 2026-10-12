"""Tek bir tezin denetimi: bayt → rapor JSON. İş yürütücü bunu ayrı bir süreçte çalıştırır.

Dönüş yalnızca rapor (metin içermez; başlık yolları dahil) ya da hata kodudur.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Literal, TypedDict

from synora.annotate import annotate_document
from synora.check import check
from synora.errors import SynoraError
from synora.fix import fix_document
from synora.ingest import open_docx
from synora.locate import locations
from synora.log import log_event
from synora.parse import parse_package
from synora.report import to_json
from synora.ruleset import load_ruleset


class PipelineResult(TypedDict):
    report: str | None
    error_code: str | None
    source_sha256: str | None


class OutputResult(TypedDict):
    docx: bytes | None
    error_code: str | None


OutputKind = Literal["fixed", "annotated"]


def run_output(
    kind: OutputKind, data: bytes, ruleset_path: str, job_id: str = "job"
) -> OutputResult:
    """Düzeltilmiş ya da yorumlu kopyayı üretir. Sonuç doğrudan kullanıcıya akar, saklanmaz."""
    try:
        rules = load_ruleset(ruleset_path)
        docx = (fix_document(data, rules).docx if kind == "fixed"
                else annotate_document(data, rules))
    except SynoraError as exc:
        log_event("output.rejected", job_id=job_id, code=exc.code.value)
        return {"docx": None, "error_code": exc.code.value}
    except Exception:
        log_event("output.crashed", job_id=job_id, code="INTERNAL")
        return {"docx": None, "error_code": "INTERNAL"}
    log_event("output.done", job_id=job_id, code=kind)
    return {"docx": docx, "error_code": None}


def run_pipeline(data: bytes, ruleset_path: str, job_id: str = "job") -> PipelineResult:
    started = time.monotonic()
    sha = hashlib.sha256(data).hexdigest()
    try:
        rules = load_ruleset(ruleset_path)
        pkg = open_docx(data)
        doc = parse_package(pkg)
        result = check(doc, rules)
        report = json.loads(to_json(result, rules))
        where = locations(doc, result.roles)
        for f in report["findings"]:
            f["location"] = where.get(f["para_id"]) if f["para_id"] else None
    except SynoraError as exc:
        log_event("job.rejected", job_id=job_id, code=exc.code.value)
        return {"report": None, "error_code": exc.code.value, "source_sha256": sha}
    except Exception:
        # Ayrıntı (ve olası belge parçaları) log'a yazılmaz; yalnızca tür.
        log_event("job.crashed", job_id=job_id, code="INTERNAL")
        return {"report": None, "error_code": "INTERNAL", "source_sha256": sha}
    log_event("job.done", job_id=job_id,
              duration_ms=int((time.monotonic() - started) * 1000),
              count=len(report["findings"]))
    return {"report": json.dumps(report, ensure_ascii=False), "error_code": None,
            "source_sha256": sha}
