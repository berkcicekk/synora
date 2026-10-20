"""Çok sayıda kılavuz: Türkçe sıralama, üniversiteye göre gruplama, varsayılan, arama kutusu."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_web import login

from synora.web.app import (
    create_app,
    discover_rulesets,
    group_rulesets,
    order_rulesets,
    tr_sort_key,
)
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
ALL = discover_rulesets(ROOT / "rulesets")


def test_turkish_alphabetical_order() -> None:
    names = ["Zonguldak", "Şırnak", "İstanbul", "Iğdır", "Çukurova", "Özyeğin", "Uşak", "Ege",
             "Ankara Üniversitesi", "Ankara Bilim", "Ünye", "Egeli", "Ege Üniversitesi"]
    assert sorted(names, key=tr_sort_key) == [
        "Ankara Bilim", "Ankara Üniversitesi", "Çukurova", "Ege", "Ege Üniversitesi", "Egeli",
        "Iğdır", "İstanbul", "Özyeğin", "Şırnak", "Uşak", "Ünye", "Zonguldak"]


def test_default_ruleset_first_example_last() -> None:
    ordered = order_rulesets(ALL, "zbeu-tip")
    assert ordered[0].id == "zbeu-tip"
    assert ordered[-1].id == "example"
    rest = [r.name for r in ordered[1:-1]]
    assert rest == sorted(rest, key=tr_sort_key)


def test_unknown_default_falls_back_to_alphabetical() -> None:
    ordered = order_rulesets(ALL, "boyle-bir-kilavuz-yok")
    assert ordered[0].id != "example"
    assert [r.id for r in ordered] == [r.id for r in order_rulesets(ALL, "")]


def test_groups_by_institution_in_turkish_order() -> None:
    groups = group_rulesets(order_rulesets(ALL, "zbeu-tip"))
    labels = [g.institution for g in groups]
    assert labels[-1] == "Diğer"  # kurumu yazılmamış örnek kural seti
    assert labels[:-1] == sorted(labels[:-1], key=tr_sort_key)
    assert len(labels) == len(set(labels))
    zbeu = next(g for g in groups if g.institution == "Zonguldak Bülent Ecevit Üniversitesi")
    assert "zbeu-tip" in [r.id for r in zbeu.items]
    assert sum(len(g.items) for g in groups) == len(ALL)


def test_upload_page_grouped_select_with_default(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    page = client.get("/").text
    select = page[page.index('<select id="ruleset"'):page.index("</select>")]
    assert '<optgroup label="Zonguldak Bülent Ecevit Üniversitesi">' in select
    assert re.findall(r'<option value="([^"]+)" selected>', select) == ["zbeu-tip"]
    assert select.count("<option") == len(ALL)
    assert re.search(r'<input id="ruleset-filter"[^>]*\shidden>', page)  # JS açar
    assert 'id="latex-link" class="textlink" href="/sablon/zbeu-tip/latex.zip" download' in page


def test_default_ruleset_setting(settings: Settings, mailer: ConsoleMailer) -> None:
    with TestClient(create_app(replace(settings, default_ruleset="odtu-fbe"), mailer)) as c:
        login(c, mailer)
        page = c.get("/").text
    assert re.findall(r'<option value="([^"]+)" selected>', page) == ["odtu-fbe"]
    assert 'href="/sablon/odtu-fbe/latex.zip"' in page


def test_settings_reads_default_ruleset_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().default_ruleset == "zbeu-tip"
    monkeypatch.setenv("SYNORA_DEFAULT_RULESET", "ankara-fbe")
    assert Settings.from_env().default_ruleset == "ankara-fbe"


def test_every_ruleset_has_source_and_institution() -> None:
    for r in ALL.values():
        if r.id == "example":
            continue
        assert r.rules.institution and r.rules.source and r.rules.source_url, r.id


def test_word_template_download(client: TestClient) -> None:
    res = client.get("/sablon/example/sablon.docx")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert res.content[:2] == b"PK"
    assert client.get("/sablon/yok-boyle-set/sablon.docx").status_code == 404
