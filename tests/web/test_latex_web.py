"""LaTeX şablonunun web'den indirilmesi (A9 /sablon/{id}/latex.zip, A11 yükleme sayfası)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from test_web import login

from synora.latex import build_zip
from synora.ruleset import load_ruleset
from synora.web.mailer import ConsoleMailer

ROOT = Path(__file__).resolve().parents[2]


def test_template_zip_download(client: TestClient) -> None:
    res = client.get("/sablon/zbeu-tip/latex.zip")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert res.headers["content-disposition"] == 'attachment; filename="payper-zbeu-tip-latex.zip"'
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.content == build_zip(load_ruleset(ROOT / "rulesets" / "zbeu-tip.yaml"))
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert "synora-zbeu-tip.cls" in zf.namelist()


def test_template_needs_no_login_and_unknown_is_404(client: TestClient) -> None:
    assert client.get("/sablon/example/latex.zip").status_code == 200
    for bad in ("yok", "..%2F..%2Fetc", "zbeu-tip.yaml", "ZBEU-TIP"):
        assert client.get(f"/sablon/{bad}/latex.zip").status_code == 404, bad


def test_upload_page_offers_template(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    page = client.get("/yukle").text
    assert "LaTeX ile mi yazıyorsunuz?" in page
    # Tek bağlantı: seçili kılavuzu izler (app.js), başlangıçta varsayılan kılavuz.
    assert 'id="latex-link" class="textlink" href="/sablon/zbeu-tip/latex.zip" download' in page
    assert "Resmi bir şablon değildir" in page
