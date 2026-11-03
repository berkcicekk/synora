"""Ana sayfa metinleri ve yerleşimi: tek terim, doğru sayılar, SSS, kırık bağlantı yok."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import synora.web.app as app_module
from synora.web.app import create_app, discover_rulesets
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src/synora/web/static"
ALL = discover_rulesets(ROOT / "rulesets")
THESIS_SETS = [r for r in ALL.values() if r.rules.kind == "thesis" and r.rules.institution]
UNIVERSITIES = {r.rules.institution for r in THESIS_SETS}


@pytest.fixture
def home(client: TestClient) -> str:
    return client.get("/").text


def text_of(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# --- Sayılar --------------------------------------------------------------------------------------


def test_counts_exclude_sample_and_journal_sets(home: str) -> None:
    assert len(ALL) - len(THESIS_SETS) == 2  # example + dergi
    stats = home.split('class="guide-stats')[1]
    assert f'<span class="n">{len(THESIS_SETS)}</span>' in stats
    assert f'<span class="n">{len(UNIVERSITIES)}</span>' in stats
    assert "Tez kılavuzlarından çıkarılmış kural seti" in stats
    assert "Kılavuzu eklenmiş üniversite" in stats
    assert "Kural setleri enstitülerce doğrulanmamıştır." in home


def test_guide_paragraph_is_one_accurate_statement(home: str) -> None:
    section = text_of(home.split('id="kilavuz"')[1].split('class="guide-dl"')[0])
    assert section.count("Zonguldak Bülent Ecevit Üniversitesi (ZBEÜ)") == 1
    assert "Pilot, Zonguldak Bülent Ecevit Üniversitesi (ZBEÜ) Tıp Fakültesi'nde yürütülecek" in \
        section.replace("&#39;", "'")
    assert f"{len(UNIVERSITIES)} üniversitenin kılavuzundan kural seti çıkarıldı." in section
    assert "Örnek kılavuz" in section


def test_full_university_name_comes_before_abbreviation(home: str) -> None:
    body = text_of(home.split("<main")[1])
    assert body.index("Zonguldak Bülent Ecevit Üniversitesi (ZBEÜ)") <= body.index("ZBEÜ")


def test_accuracy_wording_names_the_real_test(home: str) -> None:
    assert "37 resmî şablonda, kasıtlı yapılan 1.840 bozmayla ölçüldü" in home
    assert "bozma testi" not in home
    assert '<span class="n">%97,1</span>' in home


def test_stat_labels_start_with_capital(home: str) -> None:
    labels = re.findall(r'<span class="t">([^<]+)</span>', home.split('class="guide-stats')[1])
    assert len(labels) == 3 and all(label[0].isupper() for label in labels)


def test_upload_note_and_llms_use_same_counts(client: TestClient, mailer: ConsoleMailer) -> None:
    from test_web import login

    llms = client.get("/llms.txt").text
    assert f"{len(UNIVERSITIES)} üniversitenin {len(THESIS_SETS)} kural seti" in llms
    assert "250 üniversite" not in llms
    login(client, mailer)
    note = client.get("/yukle").text
    assert f"{len(UNIVERSITIES)} üniversite, {len(THESIS_SETS)} tez kılavuzu" in note


# --- Tek terim ve düğmeler ------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/giris", "/kayit", "/fiyatlandirma"])
def test_stage_term_is_pilot_everywhere(client: TestClient, path: str) -> None:
    html = client.get(path).text
    assert "Pilot aşamasında" in html and "est aşamasında" not in html


def test_cta_names_are_unified(home: str) -> None:
    labels = re.findall(r'<span class="lbl">([^<]+)</span>', home.split("</main>")[0])
    assert "Başlayın" not in labels and labels.count("Hemen başla") == 3


def test_hero_offers_sample_report_and_free_note(home: str) -> None:
    hero = home.split('id="top"')[1].split("</section>")[0]
    assert re.search(r'<a class="btn" href="/demo"><span class="lbl">Örnek raporu gör</span>', hero)
    assert "Giriş yap" not in hero and "Önce örnek raporu" not in hero
    assert "Denetim için giriş gerekir · Pilot süresince üniversite e-postasıyla ücretsiz" in hero


def test_lone_decor_squares_are_gone(home: str) -> None:
    assert "hero-px" not in home
    assert "hero-px" not in (STATIC / "app.css").read_text(encoding="utf-8")


def test_ai_note_is_present_tense(home: str) -> None:
    note = text_of(home.split('class="hiw-note')[1].split("</p>")[0])
    assert "kurallara çevirirken kullanılır" in note and "kullanıldı" not in note


def test_footer_explains_tracked_changes(home: str) -> None:
    footer = text_of(home.split('class="footer"')[1])
    assert ("Yazdıklarınıza dokunulmaz; yalnızca biçim önerileri izlenen değişiklik olarak gelir, "
            "kabul etmek size kalır.") in footer
    assert "Metniniz değiştirilmez" not in footer


# --- Adım grubu -----------------------------------------------------------------------------------


def test_check_steps_are_grouped_under_denetle(home: str) -> None:
    group = home.split('class="hiw-group"')[1].split('<span class="tno">05</span>')[0]
    assert ">Denetle<" in group
    for number in ("02", "03", "04"):
        assert f'<span class="tno">{number}</span>' in group
    assert '<span class="tno">01</span>' not in group


# --- Görsel alanı ---------------------------------------------------------------------------------


def test_barcode_stays_until_report_image_exists(home: str) -> None:
    assert 'id="barcode"' in home and "hero-shot" not in home


def test_report_image_replaces_barcode_when_added(settings: Settings, mailer: ConsoleMailer,
                                                  monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    image = tmp_path / "rapor.webp"
    image.write_bytes(b"x")
    monkeypatch.setattr(app_module, "HERO_SHOT", image)
    with TestClient(create_app(settings, mailer)) as client:
        html = client.get("/").text
    assert 'class="wrap hero-shot"' in html and 'id="barcode"' not in html
    assert 'width="2400" height="1350"' in html and 'alt="' in html.split("hero-shot")[1]


# --- SSS ------------------------------------------------------------------------------------------


def test_faq_comes_before_closing_with_code_backed_answers(home: str,
                                                           settings: Settings) -> None:
    assert home.index('id="sss"') < home.index('id="basla"')
    faq = text_of(home.split('id="sss"')[1].split('id="basla"')[0])
    for question in ("Hangi dosya türleri destekleniyor?", "Dosya boyutu sınırı var mı?",
                     "Denetim ne kadar sürer?", "Üniversitem listede yoksa ne yapabilirim?",
                     "Raporum ne zaman silinir?"):
        assert question in faq
    assert ".docx" in faq and ".docm" in faq
    assert f"En fazla {settings.max_upload_bytes // 1024**2} MB" in faq
    assert f"Günde en çok {settings.max_daily_jobs} denetim" in faq
    assert f"en çok {int(settings.job_timeout_seconds // 60)} dakika" in faq
    assert f"{int(settings.retention_hours)} saat sonra" in faq
    assert "İstek / Öneri" in faq
    assert home.split('id="sss"')[1].split('id="basla"')[0].count('<details class="faq-item"') == 5


# --- Okunabilirlik --------------------------------------------------------------------------------


def test_step_text_is_readable() -> None:
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    step = re.search(r"\.hiw-step p \{([^}]*)\}", css)
    assert step and "font-size: .875rem" in step.group(1) and "var(--ink-2)" in step.group(1)
    diagram = re.search(r"\.hiw svg text \{([^}]*)\}", css)
    assert diagram and "font-size: 14px" in diagram.group(1)


# --- Kılavuz diyagramı ----------------------------------------------------------------------------


def test_diagram_labels_are_outside_the_page(home: str) -> None:
    figure = home.split('class="guide-fig"')[1].split("</figure>")[0]
    assert 'class="guide-chips"' in figure
    assert figure.index('id="guide-page"') < figure.index('class="guide-chips"')
    assert "dim-right" in figure and "chip-4" not in figure and "data-v" not in figure


def test_only_footer_links_that_exist(client: TestClient, home: str) -> None:
    footer = home.split('class="footer"')[1]
    for href in re.findall(r'href="(/[^"#]*)"', footer):
        assert client.get(href).status_code == 200, href
    for missing in ("/iletisim", "/kullanim-kosullari", "/cerez-politikasi"):
        assert client.get(missing).status_code == 404
        assert missing not in footer
