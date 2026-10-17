"""A11 arayüz: erişilebilirlik (kontrast, odak, etiketler), akış netliği, hata ve boş durumlar.

Sunucu tarafı HTML ve statik CSS/JS üzerinden denetlenir; tarayıcı gerekmez.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
from test_web import login

from synora.web.mailer import ConsoleMailer

STATIC = Path(__file__).resolve().parents[2] / "src" / "synora" / "web" / "static"
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")


# --- Kontrast (WCAG 2.2 AA) -----------------------------------------------------------------


def _tokens() -> dict[str, str]:
    root = CSS.split(":root {", 1)[1].split("}", 1)[0]
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", root))


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# (ön plan, arka plan) — metin için 4,5:1
TEXT_PAIRS = [
    ("ink", "paper"), ("ink", "card"), ("muted", "paper"), ("muted", "card"), ("muted", "desk"),
    ("muted", "wash"), ("blue", "paper"), ("blue", "card"), ("blue", "wash"), ("blue", "desk"),
    ("error", "card"), ("error", "error-wash"), ("warning", "card"), ("warning", "warning-wash"),
    ("ok", "card"), ("on-blue", "blue"), ("on-blue-soft", "blue"), ("cyan", "night"),
]
# Odak çerçevesi (WCAG 1.4.11, metin dışı öğe) için 3:1
FOCUS_PAIRS = [("blue", "paper"), ("blue", "card"), ("blue", "desk"), ("cyan", "blue"),
               ("cyan", "night")]


def test_text_color_pairs_meet_aa() -> None:
    t = _tokens()
    bad = [(fg, bg, round(contrast(t[fg], t[bg]), 2)) for fg, bg in TEXT_PAIRS
           if contrast(t[fg], t[bg]) < 4.5]
    assert bad == []


def test_focus_ring_pairs_meet_non_text_contrast() -> None:
    t = _tokens()
    bad = [(fg, bg) for fg, bg in FOCUS_PAIRS if contrast(t[fg], t[bg]) < 3]
    assert bad == []


def test_placeholder_text_is_readable() -> None:
    color = re.search(r"input::placeholder \{ color: (#[0-9A-Fa-f]{6}); \}", CSS)
    assert color, "placeholder rengi bulunamadı"
    assert contrast(color.group(1), _tokens()["card"]) >= 4.5


def test_cyan_focus_only_on_dark_surfaces() -> None:
    # Camgöbeği odak çerçevesi fildişi zeminde 1,6:1 kalır; tanıtımın açık bölümlerinde mavi olmalı.
    assert ".landing :focus-visible { outline-color: var(--cyan); }" not in CSS
    rule = re.search(r"([^{}]+)\{ outline-color: var\(--cyan\); \}", CSS)
    assert rule, "koyu yüzeyler için camgöbeği odak kuralı yok"
    selectors = rule.group(1)
    for dark in (".hero", ".products", ".join", ".footer"):
        assert dark in selectors
    assert ".join-card :focus-visible { outline-color: var(--blue); }" in CSS


# --- Klavye ve yardımcı teknoloji -------------------------------------------------------------


def test_upload_page_works_without_surprises(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    html = client.get("/").text
    assert "<noscript>" in html  # yükleme JavaScript ister; söylenmeli
    assert 'aria-describedby="drop-help"' in html
    assert 'id="drop-help"' in html


def test_output_panel_returns_focus_and_exposes_state() -> None:
    # Panel kapanınca odak, paneli açan düğmeye döner; düğmeler panelin açık olduğunu bildirir.
    assert "aria-expanded" in JS
    assert "opener.focus()" in JS
