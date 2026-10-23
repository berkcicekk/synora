"""Ana sayfa (girişsiz) ve panel: yükleme önizlemesi yok, "nasıl çalışır" bölümü, hareket
kuralları (azaltılmış hareket, dokunmatik, CSP, token), panelde "hazır" kartı."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi.testclient import TestClient
from test_web import bad_thesis, login, upload, wait_done

from synora.web.db import Database
from synora.web.mailer import ConsoleMailer

STATIC = Path(__file__).resolve().parents[2] / "src" / "synora" / "web" / "static"
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
LANDING_JS = STATIC / "landing.js"


def _block(marker: str) -> str:
    """app.css içinde /* == AD == */ … /* == /AD == */ arasındaki yeni kod."""
    m = re.search(rf"/\* == {marker} == \*/(.*?)/\* == /{marker} == \*/", CSS, re.S)
    assert m, f"CSS bloğu yok: {marker}"
    return m.group(1)


# --- 1. Yükleme önizlemesi kalktı, giriş zorunlu ---------------------------------------------


def test_landing_has_no_upload_panel(client: TestClient) -> None:
    html = client.get("/").text
    assert 'type="file"' not in html
    assert 'id="pv-' not in html


def test_landing_calls_to_sign_in(client: TestClient) -> None:
    html = client.get("/").text
    hero = html[html.index('class="hero"'):html.index("</section>")]
    assert 'href="/kayit"' in hero and 'href="/giris"' in hero


def test_signed_in_user_lands_on_panel(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    html = client.get("/").text
    assert "Son denetimler" in html and 'class="hero"' not in html


# --- 3. "En sık yapılan biçim hataları" kalktı -----------------------------------------------


def test_top_findings_section_removed_even_with_data(client: TestClient) -> None:
    db: Database = client.app.state.db  # type: ignore[attr-defined]
    db.add_finding_counts("example", {"body.line_spacing": 500, "page.margin.left": 300})
    html = client.get("/").text
    assert "En sık yapılan" not in html and 'id="sik-hatalar"' not in html
    assert not hasattr(Database, "top_findings")  # yalnızca bu bölümü besleyen sorgu da silindi


# --- 4. "Arka planda nasıl çalışır?" ---------------------------------------------------------


def test_how_it_works_has_five_accessible_steps(client: TestClient) -> None:
    html = client.get("/").text
    sec = html[html.index('id="nasil"'):]
    sec = sec[:sec.index("</section>")]
    steps = re.findall(r'<li class="hiw-step[^"]*"', sec)
    assert len(steps) == 5
    for title in ("Yükle", "Ölç", "Karşılaştır", "Doğrula", "Teslim et"):
        assert f">{title}<" in sec, title
    svgs = re.findall(r"<svg\b[^>]*>", sec)
    assert len(svgs) == 5
    for svg in svgs:
        assert 'role="img"' in svg
        label = re.search(r'aria-label="([^"]+)"', svg)
        assert label and len(label.group(1)) > 15, svg
    assert "kılavuzları kurallara çevirirken" in sec  # yapay zekâ notu
    assert "metninizi okumaz" in sec


def test_privacy_cells_replaced_by_how_it_works(client: TestClient) -> None:
    html = client.get("/").text
    assert 'class="privacy-cells"' not in html
    assert "yapay zekâyla" in html  # gizlilik başlığı kalır


# --- 2. Hareket: yalnızca ana sayfada, azaltılmış hareket ve dokunmatik kuralları -------------


def test_landing_script_only_on_landing(client: TestClient, mailer: ConsoleMailer) -> None:
    assert "/static/landing.js?v=" in client.get("/").text
    for path in ("/giris", "/aydinlatma", "/fiyatlandirma"):
        assert "/static/landing.js" not in client.get(path).text, path
    login(client, mailer)
    for path in ("/", "/yukle"):
        assert "/static/landing.js" not in client.get(path).text, path


def test_asset_version_covers_landing_script(client: TestClient) -> None:
    h = hashlib.sha256()
    for name in ("app.css", "app.js", "fonts.css", "landing.js"):
        h.update((STATIC / name).read_bytes())
    assert f"landing.js?v={h.hexdigest()[:10]}" in client.get("/").text


def test_landing_script_is_small_and_self_contained() -> None:
    js = LANDING_JS.read_text(encoding="utf-8")
    assert len(js.encode()) <= 12 * 1024, "landing.js bütçesi (12 KB) aşıldı"
    assert "http://" not in js and "https://" not in js  # harici kaynak yok
    assert "innerHTML" not in js and "eval(" not in js
    assert "prefers-reduced-motion: reduce" in js
    assert "(hover: hover) and (pointer: fine)" in js  # eğilme/kaydırma yalnızca farede
    assert "IntersectionObserver" in js and "requestAnimationFrame" in js


def test_motion_respects_reduced_motion_in_css() -> None:
    pattern = r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}"
    reduced = "".join(re.findall(pattern, CSS, re.S))
    for sel in (".reveal", ".hiw-", ".is-ready", ".hero-steps"):
        assert sel in reduced, f"azaltılmış harekette kapanmıyor: {sel}"


def test_new_css_uses_tokens_not_fixed_colors() -> None:
    for marker in ("HAREKET", "NASIL", "HAZIR KART"):
        block = _block(marker)
        assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", block), f"{marker}: sabit renk"
        assert not re.search(r"\brgba?\(", block), f"{marker}: sabit rgba"


def test_only_transform_and_opacity_are_animated() -> None:
    for marker in ("HAREKET", "NASIL", "HAZIR KART"):
        for trans in re.findall(r"transition:\s*([^;]+);", _block(marker)):
            flat = re.sub(r"\([^)]*\)", "", trans)  # cubic-bezier(.2, .7, …) virgülleri bölünmesin
            props = [p.strip().split()[0] for p in flat.split(",")]
            # translate: bağımsız transform özelliği (belirme), eğilmenin transform'uyla çakışmaz.
            assert set(props) <= {"transform", "translate", "opacity", "box-shadow",
                                  "background-size"}, (marker, trans)


# --- 5. Panelde "hazır" kartı ----------------------------------------------------------------


def test_ready_card_glows_until_first_job(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    html = client.get("/").text
    card = re.search(r'<article class="pcard is-ready"[^>]*>', html)
    assert card, "hazır kartı yok"
    for attr in ("data-csrf=", 'data-ruleset="', "data-ruleset-name=", "data-max="):
        assert attr in card.group(0), attr
    assert "Bırakın" in html
    job_id = upload(client, csrf, bad_thesis())
    wait_done(client, job_id)
    assert "is-ready" not in client.get("/").text


def test_ready_card_css_rotates_and_falls_back() -> None:
    block = _block("HAZIR KART")
    assert "@property --glow-a" in block and "conic-gradient" in block
    assert ".is-ready.is-drag" in block  # sürüklerken güçlenir


def test_retention_promise_follows_setting(settings, mailer) -> None:  # type: ignore[no-untyped-def]
    """Saklama süresi ayardan değişince giriş, tanıtım ve altbilgi aynı sözü verir."""
    from dataclasses import replace

    from synora.web.app import create_app

    with TestClient(create_app(replace(settings, retention_hours=6.0), mailer)) as c:
        for path in ("/", "/giris"):
            html = c.get(path).text
            assert "6 saat" in html, path
            assert "24 saat" not in html, path
