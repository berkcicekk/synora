"""F6 hazırlığı: rol düzeltmeleri, açık rızayla, metinsiz eğitim verisi olarak birikir.

Saklanan satır: özellik vektörü (ParaFeatures, str alanı yok) + seçilen rol + kural seti.
İş kimliği ve e-posta saklanmaz; rıza verilmedikçe hiçbir satır yazılmaz.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from test_web import ambiguous_thesis, login, unknown_pid, upload, wait_done

from synora.web.db import Database
from synora.web.mailer import ConsoleMailer


def db_of(client: TestClient) -> Database:
    return client.app.state.db  # type: ignore[attr-defined]


def set_role_and_recheck(client: TestClient, mailer: ConsoleMailer,
                         collect: bool) -> tuple[str, str]:
    csrf = login(client, mailer)
    data = ambiguous_thesis()
    job_id = upload(client, csrf, data)
    assert wait_done(client, job_id) == "done"
    pid = unknown_pid(client, job_id)
    body = {"roles": {pid: "body"}, "collect": collect}
    res = client.post(f"/jobs/{job_id}/roles", json=body, headers={"X-CSRF-Token": csrf})
    assert res.status_code == 200, res.text
    res = client.post(f"/jobs/{job_id}/recheck", content=data, headers={
        "X-CSRF-Token": csrf, "Content-Type": "application/octet-stream"})
    assert res.status_code == 202, res.text
    assert wait_done(client, job_id) == "done"
    return job_id, csrf


def test_consented_role_fix_stores_featurevector_without_text(
        client: TestClient, mailer: ConsoleMailer) -> None:
    set_role_and_recheck(client, mailer, collect=True)
    rows = db_of(client).execute(
        "SELECT features, label, ruleset FROM training").fetchall()
    assert len(rows) == 1
    features, label, ruleset = rows[0]
    assert label == "body" and ruleset == "example"
    parsed = json.loads(features)
    assert parsed  # özellik vektörü dolu
    # Metin ya da parçası yok (ParaFeatures'ta str alan olmadığı ayrıca şema testiyle zorlanır).
    assert "Araştırma" not in features and "sınırlılık" not in features


def test_without_consent_nothing_is_stored(client: TestClient, mailer: ConsoleMailer) -> None:
    set_role_and_recheck(client, mailer, collect=False)
    assert db_of(client).execute("SELECT COUNT(*) FROM training").fetchone()[0] == 0


def test_training_rows_do_not_reference_job_or_email(
        client: TestClient, mailer: ConsoleMailer) -> None:
    job_id, _ = set_role_and_recheck(client, mailer, collect=True)
    cols = [r[1] for r in db_of(client).execute("PRAGMA table_info(training)").fetchall()]
    assert "job_id" not in cols and "email" not in cols
    features = db_of(client).execute("SELECT features FROM training").fetchone()[0]
    assert job_id not in features
