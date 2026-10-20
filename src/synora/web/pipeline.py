"""Tek bir tezin denetimi: bayt → rapor JSON. İş yürütücü bunu ayrı bir süreçte çalıştırır.

Dönüş yalnızca rapor (metin içermez; başlık yolları dahil) ya da hata kodudur.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Literal, TypedDict

from synora.annotate import annotate_document
from synora.check import USER_ROLES, CheckResult, check
from synora.errors import SynoraError
from synora.features import extract_features
from synora.fix import fix_document
from synora.ingest import open_docx
from synora.locate import locations
from synora.log import log_event
from synora.model import DocModel, Role
from synora.outline import build_outline
from synora.parse import parse_package
from synora.report import to_json
from synora.ruleset import Ruleset, load_ruleset


class PipelineResult(TypedDict):
    report: str | None
    error_code: str | None
    source_sha256: str | None
    # Öğrencinin uygulanmış rol seçimleri için (features_json, rol, kural seti) satırları.
    # Metin içermez; yalnızca rızası olan işlerde veritabanına yazılır (F6).
    training: list[tuple[str, str, str]]


class OutputResult(TypedDict):
    docx: bytes | None
    error_code: str | None


OutputKind = Literal["fixed", "annotated"]


def parse_user_roles(raw: dict[str, str] | None) -> dict[str, Role]:
    """Saklanan/gelen seçimleri doğrular; izinli olmayan değerler atılır."""
    allowed = {r.value: r for r in USER_ROLES}
    return {pid: allowed[v] for pid, v in (raw or {}).items()
            if isinstance(pid, str) and isinstance(v, str) and v in allowed}


def run_output(
    kind: OutputKind, data: bytes, ruleset_path: str, job_id: str = "job",
    user_roles: dict[str, str] | None = None,
) -> OutputResult:
    """Düzeltilmiş ya da yorumlu kopyayı üretir. Sonuç doğrudan kullanıcıya akar, saklanmaz."""
    try:
        rules = load_ruleset(ruleset_path)
        roles = parse_user_roles(user_roles)
        docx = (fix_document(data, rules, roles).docx if kind == "fixed"
                else annotate_document(data, rules, roles))
    except SynoraError as exc:
        log_event("output.rejected", job_id=job_id, code=exc.code.value)
        return {"docx": None, "error_code": exc.code.value}
    except Exception:
        log_event("output.crashed", job_id=job_id, code="INTERNAL")
        return {"docx": None, "error_code": "INTERNAL"}
    log_event("output.done", job_id=job_id, code=kind)
    return {"docx": docx, "error_code": None}


def training_rows(doc: DocModel, result: CheckResult, rules: Ruleset) -> list[tuple[str, str, str]]:
    """Uygulanan rol seçimlerinden eğitim satırları (F6): özellik vektörü + rol + kural seti.

    ParaFeatures'ta str alan yoktur (şema testiyle zorlanır); metin, iş kimliği ve e-posta
    bu satırlara hiç girmez. Rıza denetimi yazma anında yapılır (worker).
    """
    if not result.user_roles:
        return []
    features = extract_features(doc)
    out: list[tuple[str, str, str]] = []
    for pid, role in result.user_roles.items():
        f = features.get(pid)
        if f is not None:
            out.append((f.model_dump_json(), role.value, rules.ruleset))
    return out


def run_pipeline(
    data: bytes, ruleset_path: str, job_id: str = "job",
    user_roles: dict[str, str] | None = None,
) -> PipelineResult:
    started = time.monotonic()
    sha = hashlib.sha256(data).hexdigest()
    try:
        rules = load_ruleset(ruleset_path)
        pkg = open_docx(data)
        doc = parse_package(pkg)
        result = check(doc, rules, parse_user_roles(user_roles))
        report = json.loads(to_json(result, rules))
        report["user_roles"] = {pid: r.value for pid, r in result.user_roles.items()}
        where = locations(doc, result.roles)
        blocks, finding_block = build_outline(doc, result)
        report["document"] = blocks  # editör görünümü: gövde metni içermez
        for i, f in enumerate(report["findings"]):
            f["location"] = where.get(f["para_id"]) if f["para_id"] else None
            f["block"] = finding_block.get(i)
    except SynoraError as exc:
        log_event("job.rejected", job_id=job_id, code=exc.code.value)
        return {"report": None, "error_code": exc.code.value, "source_sha256": sha, "training": []}
    except Exception:
        # Ayrıntı (ve olası belge parçaları) log'a yazılmaz; yalnızca tür.
        log_event("job.crashed", job_id=job_id, code="INTERNAL")
        return {"report": None, "error_code": "INTERNAL", "source_sha256": sha, "training": []}
    log_event("job.done", job_id=job_id,
              duration_ms=int((time.monotonic() - started) * 1000),
              count=len(report["findings"]))
    return {"report": json.dumps(report, ensure_ascii=False), "error_code": None,
            "source_sha256": sha, "training": training_rows(doc, result, rules)}
