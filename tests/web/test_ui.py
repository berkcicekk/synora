"""A11 arayüz: erişilebilirlik (kontrast, odak, etiketler), akış netliği, hata ve boş durumlar.

Sunucu tarafı HTML ve statik CSS/JS üzerinden denetlenir; tarayıcı gerekmez.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_web import ambiguous_thesis, bad_thesis, login, upload, wait_done
from thesis import thesis

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


# --- Akış netliği ------------------------------------------------------------------------------


def _current_step(html: str) -> str:
    m = re.search(
        r'<li class="step[^"]*" aria-current="step">\s*<span class="step-n"[^>]*>(\d)</span>', html)
    assert m, "akış göstergesi yok"
    return m.group(1)


def test_upload_page_shows_step_one_and_privacy(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    html = client.get("/").text
    assert _current_step(html) == "1"
    # Mimari §10.1: yükleme ekranında gizlilik notu
    for promise in ("Metniniz değiştirilmez.", "Yapay zekâ tarafından okunmaz.",
                    "Dosyanız işlem bitince silinir."):
        assert promise in html
    assert "Yüklemeden önce" in html
    assert "Farklı Kaydet" in html


def test_processing_page_shows_step_two(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    db = client.app.state.db  # type: ignore[attr-defined]
    db.add_job("bekleyen-is-00000001", "ogrenci@beun.edu.tr", "example")
    html = client.get("/jobs/bekleyen-is-00000001").text
    assert _current_step(html) == "2"
    assert "Teziniz denetleniyor." in html
    assert 'href="/">Belgelerim</a>' in html


def _corrupted_docx() -> bytes:
    data = bytearray(thesis())
    data[200] ^= 0xFF  # sıkıştırılmış veride tek bayt: zip açılır, part okunamaz
    return bytes(data)


@pytest.mark.parametrize(("data", "code", "hint"), [
    (b"bu bir word belgesi degil", "NOT_A_ZIP", "Word Belgesi (.docx)"),
    (_corrupted_docx(), "CORRUPT_ZIP", "Word onarmayı önerirse"),
], ids=["not-a-zip", "corrupt-zip"])
def test_failed_job_explains_what_to_do(client: TestClient, mailer: ConsoleMailer,
                                        data: bytes, code: str, hint: str) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, data)
    assert wait_done(client, job_id) == "failed"
    html = client.get(f"/jobs/{job_id}").text
    assert f"Kod: {code}" in html
    assert "Ne yapabilirsiniz?" in html
    assert hint in html
    assert "step now failed" in html
    assert "(başarısız)" in html


# --- Rapor ekranı: özet, sıradaki adımlar, Word'de nasıl düzeltilir ---------------------------


def _done_job(client: TestClient, mailer: ConsoleMailer, data: bytes) -> str:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, data)
    assert wait_done(client, job_id) == "done"
    return job_id


def test_report_digest_buckets_and_next_steps(client: TestClient, mailer: ConsoleMailer) -> None:
    job_id = _done_job(client, mailer, bad_thesis())
    html = client.get(f"/jobs/{job_id}").text
    digest = html.split('class="digest"', 1)[1].split("</section>", 1)[0]
    assert "1 hata, 0 uyarı." in digest  # telefonda araç çubuğu özeti gizli; burada görünür
    fix = digest.split('class="bucket b-fix"', 1)[1].split("</li>", 1)[0]
    manual = digest.split('class="bucket b-manual"', 1)[1].split("</li>", 1)[0]
    assert '<span class="b-num">1</span>' in fix
    assert '<span class="b-num">0</span>' in manual and "disabled" in manual
    assert "Kontrol edin" not in digest  # belirsiz paragraf yok
    assert "Sıradaki adımlar" in digest
    assert "Tümünü Kabul Et" in digest
    assert 'data-filter="manual"' in html
    assert "Düzeltilmiş kopyada otomatik düzeltilir." in html
    assert "Word'de nasıl düzeltilir" in html
    assert "Satır Aralığı Seçenekleri" in html  # body.line_spacing bulgusu
    assert "son onayı" in html  # resmi kontrolün yerini almaz


def test_report_digest_points_to_unsure_paragraphs(client: TestClient,
                                                   mailer: ConsoleMailer) -> None:
    job_id = _done_job(client, mailer, ambiguous_thesis())
    html = client.get(f"/jobs/{job_id}").text
    check = html.split('class="bucket b-check"', 1)[1].split("</li>", 1)[0]
    assert "Kontrol edin" in check and "data-jump-unsure" in check
    assert "türünü seçip yeniden denetleyin" in html


def test_clean_report_has_no_digest(client: TestClient, mailer: ConsoleMailer) -> None:
    job_id = _done_job(client, mailer, thesis())
    html = client.get(f"/jobs/{job_id}").text
    assert 'class="digest"' not in html
    assert "Kılavuza aykırı biçim bulunamadı." in html


@pytest.mark.parametrize(("rule_id", "keyword"), [
    ("document.tracked_changes", "Tümünü Kabul Et"),
    ("page.size", "A4"),
    ("page.margin.left", "Kenar Boşlukları"),
    ("page_numbering.formats", "Sayfa Numaralarını Biçimlendir"),
    ("page_numbering.position", "Sayfa Numarası"),
    ("page_numbering.decoration", "parantez"),
    ("table_caption.position", "Resim Yazısı Ekle"),
    ("heading_1.case", "Büyük/Küçük Harf"),
    ("body.font", "Yazı Tipi kutusundan"),
    ("body.size_pt", "Yazı Tipi Boyutu"),
    ("heading_1.bold", "Ctrl+B"),
    ("body.alignment", "Ctrl+J"),
    ("body.line_spacing", "Satır Aralığı Seçenekleri"),
    ("body.first_line_indent_cm", "Girinti"),
    ("body.space_after_pt", "nk = punto"),
    ("heading_1.page_break_before", "Satır ve Sayfa Sonları"),
])
def test_word_howto_for_each_rule_family(rule_id: str, keyword: str) -> None:
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(STATIC.parent / "templates")), autoescape=True)
    html = env.from_string('{% from "_howto.html" import howto %}{{ howto(r) }}').render(r=rule_id)
    assert "Word'de nasıl düzeltilir" in html
    assert keyword in html


def test_no_congratulations_while_paragraphs_unchecked(client: TestClient,
                                                       mailer: ConsoleMailer) -> None:
    job_id = _done_job(client, mailer, ambiguous_thesis())
    html = client.get(f"/jobs/{job_id}").text
    assert "Tebrikler" not in html
    assert "Türü belirsiz" in html
    assert 'class="bucket b-fix"' not in html  # bulgu yokken boş kovalar gösterilmez


def test_mobile_editor_layout_rules() -> None:
    # Telefonda araç çubuğu düğmeleri başlığın üstüne binmesin; özet ve bulgular önce gelsin.
    mobile = CSS.split("@media (max-width: 760px) {\n  body.editor", 1)[1].split("\n}", 1)[0]
    assert ".toolbar { grid-template-columns: minmax(0, 1fr);" in mobile
    assert ".toolbar-right { justify-self: stretch; flex-wrap: wrap;" in mobile
    assert ".pane-comments { order: -1; }" in mobile
    assert "pane.scrollHeight <= pane.clientHeight" in JS  # tek sütunda sayfa kayar
