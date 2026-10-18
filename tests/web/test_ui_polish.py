"""Arayüz denetimi (UI/UX Pro Max kontrol listesi) sonrası düzeltmeler: sayılar tutarlı, telefonda
dokunma ve yerleşim, form hataları alana bağlı, kontrast, uzun beklemeler."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
from test_ui import _tokens, contrast
from test_web import bad_thesis, csrf_from, login, upload, wait_done

from synora.web.mailer import ConsoleMailer

STATIC = Path(__file__).resolve().parents[2] / "src" / "synora" / "web" / "static"
TEMPLATES = STATIC.parent / "templates"
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")


def _media(query: str) -> str:
    """CSS'te verilen medya sorgusunun tüm bloklarının gövdeleri, art arda."""
    bodies, start = [], CSS.find(f"@media {query} {{")
    assert start >= 0, query
    while start >= 0:
        depth, i = 0, CSS.index("{", start)
        for j in range(i, len(CSS)):
            depth += {"{": 1, "}": -1}.get(CSS[j], 0)
            if depth == 0:
                bodies.append(CSS[i:j])
                break
        start = CSS.find(f"@media {query} {{", i)
    return "\n".join(bodies)


# --- Rapor sayfası --------------------------------------------------------------------------


def test_filter_counts_use_the_same_unit_as_the_summary(client: TestClient,
                                                        mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, bad_thesis())
    wait_done(client, job_id)
    html = client.get(f"/jobs/{job_id}").text
    tally = re.search(r"<strong>(\d+) hata, (\d+) uyarı\.</strong>", html)
    assert tally
    errors, warnings = int(tally.group(1)), int(tally.group(2))

    def fc(name: str) -> int:
        m = re.search(rf'data-filter="{name}"[^>]*>[^<]*<span class="fc">(\d+)</span>', html)
        return int(m.group(1)) if m else 0

    assert fc("error") == errors and fc("warning") == warnings
    fixable = re.search(r'data-apply-filter="fixable"[^>]*>\s*<span class="b-num">(\d+)', html)
    assert fixable and fc("fixable") == int(fixable.group(1))


def test_card_tap_on_phone_does_not_jump_to_the_page_view() -> None:
    # Tek sütunda sayfa görünümü yorumların altında: dokununca oraya kaydırmak listeyi kaybettirir.
    assert 'const singleColumn = () => matchMedia("(max-width: 760px), (max-height: 500px)")' in JS
    assert "activateCard(c, !singleColumn())" in JS


def test_report_editor_is_single_column_on_landscape_phones() -> None:
    body = _media("(max-width: 760px), (max-height: 500px)")
    assert "body.editor { height: auto; overflow: visible; }" in body
    assert ".workspace { grid-template-columns: 1fr; height: auto; }" in body
    assert "100dvh" in CSS


def test_role_select_is_touch_sized_on_phones() -> None:
    body = _media("(max-width: 760px), (max-height: 500px)")
    assert ".role-pick select { font-size: 16px; min-height: 44px; }" in body


def test_block_label_keeps_heading_text() -> None:
    job = (TEMPLATES / "job.html").read_text(encoding="utf-8")
    assert 'aria-label="{% if b.text %}{{ b.text }}: {% endif %}{{ b.cards|length }} bulgu"' in job


def test_delete_confirmation_can_be_cancelled() -> None:
    job = (TEMPLATES / "job.html").read_text(encoding="utf-8")
    assert "data-cancel-delete" in job and "Vazgeç" in job
    assert "[data-cancel-delete]" in JS


def test_processing_poll_stops_on_errors_and_after_a_while() -> None:
    poll = JS[JS.index("// --- Durum takibi"):JS.index("// --- Bulgu süzme")]
    assert "!res.ok" in poll and "application/json" in poll
    assert "beklenenden uzun" in poll and "oturumunuz sona ermiş" in poll


# --- Yükleme --------------------------------------------------------------------------------


def test_upload_copy_and_state_on_touch_devices(client: TestClient,
                                                mailer: ConsoleMailer) -> None:
    login(client, mailer)
    html = client.get("/").text
    assert 'class="t-touch"' in html and 'class="t-pointer"' in html
    assert re.search(r'<button id="submit"[^>]*aria-describedby="upload-status"', html)
    assert ".t-touch { display: inline; }" in _media("(hover: none)")
    choose = JS[JS.index("const choose = (f) => {"):JS.index('input.addEventListener("change"')]
    assert 'drop.classList.remove("has-file")' in choose
    assert "min-height: 180px" in _media("(max-width: 760px)")


# --- Giriş / kayıt / tanıtım ----------------------------------------------------------------


def test_auth_error_is_linked_to_the_field(client: TestClient) -> None:
    page = client.get("/giris")
    html = client.post("/login", data={"email": "adres-degil",
                                       "csrf": csrf_from(page.text)}).text
    assert '<p class="alert" role="alert" id="auth-error">' in html
    field = re.search(r'<input id="email"[^>]*>', html)
    assert field and 'aria-invalid="true"' in field.group(0)
    assert "auth-error" in field.group(0)
    clean = re.search(r'<input id="email"[^>]*>', client.get("/giris").text)
    assert clean and "aria-invalid" not in clean.group(0)


def test_consent_link_does_not_lose_the_form(client: TestClient) -> None:
    html = client.get("/kayit").text
    link = '<a class="textlink" href="/aydinlatma" target="_blank" rel="noopener">'
    assert link in html  # yeni sekmede açılır, yazılan e-posta kaybolmaz


def test_invalid_link_wording_covers_used_links(client: TestClient) -> None:
    html = client.get("/auth?token=yok").text
    assert "Bağlantı artık geçerli değil." in html
    assert "kullanılmış ya da süresi dolmuş" in html


def test_landing_primary_action_goes_to_register(client: TestClient) -> None:
    html = client.get("/").text
    hero = html[html.index('<div class="hero-aside">'):html.index("</section>")]
    assert 'href="/kayit"' in hero


# --- Kontrast, hedef boyutu, hareket ---------------------------------------------------------


def test_placeholder_is_readable_on_paper_too() -> None:
    color = re.search(r"input::placeholder \{ color: (#[0-9A-Fa-f]{6}); \}", CSS)
    assert color and contrast(color.group(1), _tokens()["paper"]) >= 4.5


def test_inactive_story_steps_keep_body_text_readable() -> None:
    desktop = _media("(min-width: 1000px)")
    step = re.search(r"\.story-step \{[^}]*\}", desktop)
    assert step and "opacity" not in step.group(0)  # paragraf soluklaştırılmaz
    assert ".story-step:not(.active) h3" in desktop


def test_input_borders_meet_non_text_contrast() -> None:
    assert re.search(r"\.ruleset-filter \{[^}]*border: 1px solid var\(--border\)", CSS)
    assert re.search(r"\.role-pick select \{[^}]*border: 1px solid var\(--border\)", CSS)
    assert contrast(_tokens()["border"], _tokens()["paper"]) >= 3


def test_small_links_get_touch_targets() -> None:
    body = _media("(pointer: coarse)")
    for sel in (".nav-link", ".linkbtn", ".output-close", ".back"):
        assert sel in body
    assert "min-height: 44px" in body


def test_sticky_nav_does_not_hide_focus() -> None:
    assert "scroll-padding-top" in CSS


def test_no_false_affordances_or_unguarded_motion() -> None:
    assert ".hero-logo-inner { position: relative; cursor: pointer;" not in CSS
    guard = "@media (hover: hover) and (prefers-reduced-motion: no-preference)"
    assert ".plan:hover { transform" not in CSS or guard in CSS
