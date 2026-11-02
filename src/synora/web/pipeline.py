"""Tek bir tezin denetimi: bayt → rapor JSON. İş yürütücü bunu ayrı bir süreçte çalıştırır.

Dönüş yalnızca rapor (metin içermez; başlık yolları dahil) ya da hata kodudur.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from typing import Any, Literal, TypedDict

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
from synora.report import summary, to_json
from synora.ruleset import Ruleset, load_ruleset

# Küçük bir dosya on binlerce bulgu üretebilir; rapor belleğe ve veritabanına sınırlı girer.
# Sınırlar gerçek tezlerin çok üstündedir (doğruluk testinde medyan 63 bulgu).
MAX_FINDINGS_PER_GROUP = 500
MAX_REPORT_FINDINGS = 5_000
MAX_REPORT_BYTES = 8 * 1024 * 1024
REPORT_TOO_LARGE = "REPORT_TOO_LARGE"


class PipelineResult(TypedDict):
    report: str | None
    # Panel için özet (JSON): toplam sayılar, kural başına adet. Tam rapor açılmadan okunur.
    stats: str | None
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


def limit_findings(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Raporda tutulacak bulgular ve listeye hiç giremeyen bulgu sayısı.

    Aynı türden (kural + beklenen + bulunan) fazlası, türün son tutulan bulgusunun `omitted`
    alanında sayılır; böylece ekrandaki adet gerçeği gösterir. Bulgular yerinde değiştirilir.
    """
    kept: list[dict[str, Any]] = []
    last_of_group: dict[tuple[str, str, str], dict[str, Any]] = {}
    group_sizes: Counter[tuple[str, str, str]] = Counter()
    for finding in findings:
        group = (finding["rule_id"], finding["expected"], finding["actual"])
        group_sizes[group] += 1
        if group_sizes[group] <= MAX_FINDINGS_PER_GROUP:
            kept.append(finding)
            last_of_group[group] = finding
        else:
            last = last_of_group[group]
            last["omitted"] = last.get("omitted", 0) + 1
    dropped = sum(1 + f.get("omitted", 0) for f in kept[MAX_REPORT_FINDINGS:])
    return kept[:MAX_REPORT_FINDINGS], dropped


def report_stats(result: CheckResult) -> str:
    """Kırpılmamış toplamlar; yalnızca sayı ve kural kimliği, metin içermez."""
    counts = summary(result)
    return json.dumps({
        "errors": counts["errors"], "warnings": counts["warnings"], "fixable": counts["fixable"],
        "findings": len(result.findings),
        "rule_counts": dict(Counter(f.rule_id for f in result.findings)),
    })


def _failed(error_code: str, source_sha256: str) -> PipelineResult:
    return {"report": None, "stats": None, "error_code": error_code,
            "source_sha256": source_sha256, "training": []}


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
        report["findings"], report["dropped_findings"] = limit_findings(report["findings"])
    except SynoraError as exc:
        log_event("job.rejected", job_id=job_id, code=exc.code.value)
        return _failed(exc.code.value, sha)
    except Exception:
        # Ayrıntı (ve olası belge parçaları) log'a yazılmaz; yalnızca tür.
        log_event("job.crashed", job_id=job_id, code="INTERNAL")
        return _failed("INTERNAL", sha)
    report_json = json.dumps(report, ensure_ascii=False)
    if len(report_json.encode()) > MAX_REPORT_BYTES:
        log_event("job.rejected", job_id=job_id, code=REPORT_TOO_LARGE)
        return _failed(REPORT_TOO_LARGE, sha)
    log_event("job.done", job_id=job_id,
              duration_ms=int((time.monotonic() - started) * 1000),
              count=len(result.findings))
    return {"report": report_json, "stats": report_stats(result), "error_code": None,
            "source_sha256": sha, "training": training_rows(doc, result, rules)}
