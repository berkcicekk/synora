"""Arayüz metinleri: gerçeği söyler ve yazımı doğrudur."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from synora.report import rule_label

TEMPLATES = Path(__file__).resolve().parents[2] / "src/synora/web/templates"


def template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def test_stat_does_not_claim_official_templates(client: TestClient) -> None:
    html = client.get("/").text
    assert "resmî biçim şablonu" not in html
    assert "üniversitenin yazım kılavuzu" in html


def test_landing_has_description(client: TestClient) -> None:
    assert '<meta name="description" content="Sontez, Word tezinizi' in client.get("/").text


def test_no_support_team_is_promised() -> None:
    page = template("job.html")
    assert "destek ekibine" not in page
    assert "İstek / Öneri kutusundan" in page


def test_report_text_is_described_accurately() -> None:
    assert "raporda metniniz yer almaz" not in template("panel.html")
    assert "başlık adları" in template("panel.html")
    assert "gönderilmez ve sunucuda saklanmaz" not in template("pricing.html")
    assert "tez dosyanız sunucuda saklanmaz" in template("pricing.html")


def test_pending_account_hint_holds_in_every_login_mode() -> None:
    assert "giriş yapamaz" not in template("admin_accounts.html")


@pytest.mark.parametrize(("name", "bad", "good"), [
    ("pricing.html", "kılavuza uydurmak", "kılavuza uygun hale getirmek"),
    ("_howto.html", "Önceki ile Bağlantılı", "Öncekine Bağla"),
    ("upload.html", "Resmi bir şablon", "Resmî bir şablon"),
])
def test_wording_fixes(name: str, bad: str, good: str) -> None:
    text = template(name)
    assert bad not in text and good in text


def test_paper_is_spelled_with_circumflex() -> None:
    assert rule_label("page.size") == "Kâğıt boyutu"
