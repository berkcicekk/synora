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
    page = client.get("/yukle").text
    start = page.index('<select id="ruleset"')
    select = page[start:page.index("</select>", start)]  # önünde üniversite listesi de var
    assert '<optgroup label="Zonguldak Bülent Ecevit Üniversitesi">' in select
    assert re.findall(r'<option value="([^"]+)" selected>', select) == ["zbeu-tip"]
    assert select.count("<option") == len(ALL)
    assert 'id="ruleset-field"' in page  # JS aranabilir seçiciyi buraya kurar; JS'siz select kalır
    assert 'id="latex-link" class="textlink" href="/sablon/zbeu-tip/latex.zip" download' in page


def test_default_ruleset_setting(settings: Settings, mailer: ConsoleMailer) -> None:
    with TestClient(create_app(replace(settings, default_ruleset="odtu-fbe"), mailer)) as c:
        login(c, mailer)
        page = c.get("/yukle").text
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


def test_ruleset_cascade_component_shipped() -> None:
    """Kılavuz seçimi: üniversite → kılavuz kademeli listeler (JS süzer, JS'siz tam liste)."""
    static = ROOT / "src" / "synora" / "web" / "static"
    js = (static / "app.js").read_text(encoding="utf-8")
    css = (static / "app.css").read_text(encoding="utf-8")
    assert 'getElementById("u-uni")' in js and "uni-fld" in js  # üniversite listesi JS ile açılır
    assert "uniSel.addEventListener" in js  # seçim kılavuz listesini süzer
    assert re.search(r"\.fld select \{[^}]*border: 1px solid var\(--border\)", css)
    assert re.search(r"\.fld select \{[^}]*height: 44px", css)  # dokunma hedefi


def test_word_template_download(client: TestClient) -> None:
    res = client.get("/sablon/example/sablon.docx")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert res.content[:2] == b"PK"
    assert client.get("/sablon/yok-boyle-set/sablon.docx").status_code == 404


def test_panel_shows_real_ruleset_and_upload_link(client: TestClient,
                                                  mailer: ConsoleMailer) -> None:
    """Panel: kılavuz kartı kural setinden gerçek ölçüleri gösterir; yükleme sayfası ayrı rotada."""
    login(client, mailer)
    page = client.get("/").text
    chips = re.findall(r'<span class="chip-tag">([^<]+)</span>', page)
    assert chips, "kılavuz kartında ölçü yok"
    assert "Henüz denetim yok" in page and 'href="/yukle"' in page
    assert client.get("/yukle").status_code == 200


def test_upload_route_requires_login(client: TestClient) -> None:
    res = client.get("/yukle", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/giris"
