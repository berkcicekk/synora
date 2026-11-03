"""Yükleme akışı (önce tez, sonra kılavuz), seçim kutusu, bekleme ekranı, metin görünümü sözleri."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
from test_web import bad_thesis, login, upload, wait_done

from synora.web.db import Database
from synora.web.mailer import ConsoleMailer

STATIC = Path(__file__).resolve().parents[2] / "src/synora/web/static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
APP_CSS = (STATIC / "app.css").read_text(encoding="utf-8")


def css_block(selector: str) -> str:
    found = re.search(re.escape(selector) + r" \{([^}]*)\}", APP_CSS)
    assert found, selector
    return found.group(1)


def test_test_stage_label_replaces_pilot_label(client: TestClient) -> None:
    for path in ("/", "/giris", "/kayit"):
        html = client.get(path).text
        assert '<p class="eyebrow-dot">Test aşamasında</p>' in html, path
        assert "Pilot · ZBEÜ" not in html, path


# --- Yükleme akışı --------------------------------------------------------------------------------


def test_upload_page_numbers_steps_and_hints_guide(client: TestClient,
                                                   mailer: ConsoleMailer) -> None:
    login(client, mailer)
    html = client.get("/yukle").text
    for step in ("1", "2"):
        assert re.search(rf'class="flow-no[^"]*"[^>]*>{step}<', html)
    assert 'id="guide-hint"' in html and "Önce tezinizi seçin" in html
    assert 'id="uni-search"' not in html  # arama artık açılır listenin içinde


def test_choosing_file_leads_to_guide_then_submit() -> None:
    assert 'guide.classList.add("is-next")' in APP_JS
    assert 'submit.classList.add("is-next")' in APP_JS
    assert "scrollIntoView" in APP_JS


def test_native_selects_stay_for_no_js_and_form_value(client: TestClient,
                                                      mailer: ConsoleMailer) -> None:
    login(client, mailer)
    html = client.get("/yukle").text
    assert '<select id="ruleset"' in html and "pick-btn" not in html  # picker JS ile kurulur


def test_picker_is_keyboard_accessible() -> None:
    for token in ('"aria-haspopup", "listbox"', '"aria-expanded"', '"aria-activedescendant"',
                  '"ArrowDown"', '"ArrowUp"', '"Escape"', '"role", "listbox"', '"role", "option"'):
        assert token in APP_JS, token
    assert "innerHTML = " not in APP_JS.split("--- Seçim kutusu")[1].split("--- Yükleme:")[0]


def test_picker_meets_touch_and_ios_rules() -> None:
    assert "min-height: 44px" in css_block(".pick-btn")
    assert "min-height: 44px" in css_block(".pick-list li")
    assert ".pick-search" in APP_CSS.split("@media (max-width: 760px)")[-1] or re.search(
        r"\.fld select, \.fld-search", APP_CSS)


def test_before_upload_opens_as_dialog(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    html = client.get("/yukle").text
    assert 'data-dialog-open="prep-dialog"' in html
    dialog = html.split('<dialog id="prep-dialog"')[1].split("</dialog>")[0]
    assert "Yüklemeden önce" in dialog and "data-dialog-close" in dialog and ".docm" in dialog
    assert "<summary>Yüklemeden önce</summary>" not in html
    assert ".showModal()" in APP_JS


# --- Bekleme ekranı -------------------------------------------------------------------------------


def waiting_page(client: TestClient, mailer: ConsoleMailer) -> str:
    job_id = upload(client, login(client, mailer), bad_thesis())
    assert wait_done(client, job_id) == "done"
    db: Database = client.app.state.db  # type: ignore[attr-defined]
    db.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
    return client.get(f"/jobs/{job_id}").text


def test_waiting_page_has_falling_sheets_and_keeps_polling(client: TestClient,
                                                           mailer: ConsoleMailer) -> None:
    html = waiting_page(client, mailer)
    layer = html.split('class="paperfall"')[1].split("</div>")[0]
    assert 'aria-hidden="true"' in layer and layer.count("<i>") == 24
    assert "data-poll=" in html and "Teziniz denetleniyor" in html
    assert 'role="status"' in html.split("Teziniz denetleniyor")[1]
    assert "style=" not in html.split("<main")[1].split("</main>")[0]  # CSP


def test_waiting_animation_respects_reduced_motion_and_uses_transform() -> None:
    fall = re.search(r"@keyframes sheet-fall \{(.*?)\n\}", APP_CSS, re.S)
    assert fall and "transform" in fall.group(1)
    assert not re.search(r"\b(top|left|width|height):", fall.group(1))
    reduced = "".join(re.findall(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", APP_CSS,
                                 re.S))
    assert ".paperfall" in reduced and ".scan-beam" in reduced


# --- Metin görünümü sözü --------------------------------------------------------------------------


def test_doc_view_says_it_is_not_a_download(client: TestClient, mailer: ConsoleMailer) -> None:
    job_id = upload(client, login(client, mailer), bad_thesis())
    assert wait_done(client, job_id) == "done"
    html = client.get(f"/jobs/{job_id}").text
    box = html.split('id="docview"')[1].split('id="docview-status"')[0]
    assert "Tezimi aç" not in box and "Dosyamı seç" in box
    assert "indirme" in box and "sunucuya gönderilmez" in box
