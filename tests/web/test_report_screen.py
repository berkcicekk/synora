"""Rapor ekranı: tek sayı kaynağı, terimler, ana hat toplamları, eksik bölüm, görsel kurallar."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_web import ambiguous_thesis, bad_thesis, login, upload, wait_done

from synora.web.app import _section_label, report_counts, report_view
from synora.web.mailer import ConsoleMailer

STATIC = Path(__file__).resolve().parents[2] / "src" / "synora" / "web" / "static"
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")
REQUIRED = ("İÇİNDEKİLER", "ÖNSÖZ", "ÖZET", "SUMMARY", "GİRİŞ", "GEREÇ VE YÖNTEM|GEREÇ YÖNTEM")


def finding(rule: str = "body.size_pt", *, severity: str = "error", fixable: bool = True,
            block: int | None = None, expected: str = "12", omitted: int = 0) -> dict[str, Any]:
    return {"rule_id": rule, "severity": severity, "fixable": fixable, "expected": expected,
            "actual": "11", "message": f"{rule} iletisi", "block": block, "omitted": omitted}


def report(findings: list[dict[str, Any]], blocks: list[dict[str, Any]],
           unknown: int = 0) -> dict[str, Any]:
    errors = sum((f["severity"] == "error") * (1 + f["omitted"]) for f in findings)
    warnings = sum((f["severity"] == "warning") * (1 + f["omitted"]) for f in findings)
    fixable = sum(f["fixable"] * (1 + f["omitted"]) for f in findings)
    return {"summary": {"errors": errors, "warnings": warnings, "fixable": fixable,
                        "unknown_paragraphs": unknown, "cover_paragraphs": 0},
            "ruleset": {"name": "Örnek"}, "findings": findings, "document": blocks}


def heading(text: str, kind: str = "h1") -> dict[str, Any]:
    return {"kind": kind, "text": text}


def para() -> dict[str, Any]:
    return {"kind": "para", "lines": 3, "last": 5}


def done_page(client: TestClient, mailer: ConsoleMailer, data: bytes) -> str:
    job_id = upload(client, login(client, mailer), data)
    assert wait_done(client, job_id) == "done"
    return client.get(f"/jobs/{job_id}").text


# --- B1-B5: tek kaynak ve terimler ----------------------------------------------------------------


def test_counts_come_from_summary_and_keep_check_apart() -> None:
    summary = {"errors": 22, "warnings": 1, "fixable": 13, "unknown_paragraphs": 1}
    assert report_counts(summary, [{}] * 14) == {
        "errors": 22, "warnings": 1, "total": 23, "auto": 13, "manual": 10, "check": 1,
        "comments": 14}


def test_every_surface_shows_the_same_numbers(client: TestClient) -> None:
    html = client.get("/demo").text
    tally = re.search(r"<strong>(\d+) hata, (\d+) uyarı</strong>", html)
    errors, warnings = int(tally.group(1)), int(tally.group(2))
    total = errors + warnings
    buckets = dict(re.findall(
        r'<span class="b-num">(\d+)</span>\s*<span class="b-name">([^<]+)</span>', html))
    by_name = {name: int(num) for num, name in buckets.items()}
    filters = {name: int(num) for name, num in re.findall(
        r'data-filter="\w+"[^>]*>([^<]+?) <span class="fc">(\d+)</span>', html)}
    assert filters["Tümü"] == total
    assert by_name["Otomatik"] + by_name["Elle"] == total
    assert filters.get("Otomatik", 0) == by_name["Otomatik"]
    assert filters.get("Elle", 0) == by_name["Elle"]
    assert filters.get("Hatalar", 0) == errors and filters.get("Uyarılar", 0) == warnings
    comments = len(re.findall(r'<li class="comment card', html))
    assert f"{total} bulgu · {comments} yorumda toplandı" in " ".join(html.split())


def test_report_template_does_not_compute_numbers() -> None:
    template = (STATIC.parent / "templates" / "job.html").read_text(encoding="utf-8")
    for computed in ("sum(attribute", "selectattr(\"severity\"", "s.errors + s.warnings"):
        assert computed not in template


def test_terms_are_unified(client: TestClient, mailer: ConsoleMailer) -> None:
    html = done_page(client, mailer, ambiguous_thesis())
    for old in ("Sizin düzeltmeniz gereken", "Düzeltilebilir", "düzeltilebilir", "Türü belirsiz",
                "Otomatik düzeltilir"):
        assert old not in html, old
    assert 'data-filter="check"' in html
    assert re.search(r'class="bucket b-check".*?Kontrol edin', html, re.S)
    assert "paragraf kontrol bekliyor" in html


def test_check_filter_lists_the_paragraphs(client: TestClient, mailer: ConsoleMailer) -> None:
    html = done_page(client, mailer, ambiguous_thesis())
    listing = html.split('id="check-list"')[1].split("</ul>")[0]
    assert "data-jump-block=" in listing and "hidden" in html.split('id="check-list"')[1][:20]


def test_title_tally_has_no_trailing_period(client: TestClient) -> None:
    tally = client.get("/demo").text.split('class="tally"')[1].split("</span>")[0]
    assert "uyarı</strong>" in tally and "uyarı." not in tally


# --- B6, B11: numara ve ana hat -------------------------------------------------------------------


def test_card_numbers_follow_first_appearance_in_the_document() -> None:
    blocks = [para() for _ in range(6)]
    view = report_view(report([finding("a.x", block=4), finding("b.x", block=1),
                               finding("c.x", block=2), finding("b.x", block=5)], blocks))
    assert [c["rule_id"] for c in view["cards"]] == ["b.x", "c.x", "a.x"]
    assert view["blocks"][5]["cards"] == [1]  # aynı tür, aynı numara


def test_outline_parent_total_equals_own_plus_children() -> None:
    blocks = [{"kind": "section", "n": 1}, para(), heading("ÖZET"), para(),
              heading("Alt", "h2"), para(), {"kind": "section", "n": 2}, para()]
    view = report_view(report([finding("a.x", block=1), finding("b.x", block=3),
                               finding("c.x", block=5, omitted=2), finding("d.x", block=7)],
                              blocks))
    counts = {e["text"]: e["count"] for e in view["outline"]}
    assert counts == {"Bölüm 1": 5, "ÖZET": 4, "Alt": 3, "Bölüm 2": 1}


# --- B10: eksik bölüm -----------------------------------------------------------------------------


def missing(name: str) -> dict[str, Any]:
    return finding("document.missing_section", expected=name, fixable=False)


def test_missing_section_sits_after_previous_required_section() -> None:
    blocks = [heading("ÖZET"), para(), heading("GİRİŞ"), para()]
    view = report_view(report([missing("SUMMARY")], blocks), REQUIRED)
    assert [m["label"] for m in view["blocks"][2]["missing"]] == ["Summary"]
    assert [e["text"] for e in view["outline"]] == ["ÖZET", "Eksik: Summary", "GİRİŞ"]
    assert view["cards"][0]["targets"] == ["m0"]


def test_missing_section_is_not_counted_on_the_first_block() -> None:
    blocks = [{"kind": "section", "n": 1}, heading("ÖZET"), para(), heading("GİRİŞ")]
    found = missing("SUMMARY")
    found["block"] = 0  # belge düzeyi bulgular raporda ilk bloğa bağlanır
    view = report_view(report([found], blocks), REQUIRED)
    assert view["blocks"][0]["cards"] == []
    assert {e["text"]: e["count"] for e in view["outline"]}["Bölüm 1"] == 1


def test_missing_section_without_previous_goes_to_the_start() -> None:
    blocks = [heading("GİRİŞ"), para()]
    view = report_view(report([missing("ÖNSÖZ")], blocks), REQUIRED)
    assert [m["label"] for m in view["blocks"][0]["missing"]] == ["Önsöz"]


def test_missing_section_at_the_start_belongs_to_the_first_section() -> None:
    blocks = [{"kind": "section", "n": 1}, heading("GİRİŞ"), para()]
    view = report_view(report([missing("ÖNSÖZ")], blocks), REQUIRED)
    assert [e["text"] for e in view["outline"]] == ["Bölüm 1", "Eksik: Önsöz", "GİRİŞ"]
    assert view["outline"][0]["count"] == 1


def test_last_missing_section_goes_after_the_document() -> None:
    blocks = [heading("GİRİŞ"), para()]
    view = report_view(report([missing("GEREÇ VE YÖNTEM")], blocks), REQUIRED)
    assert [m["label"] for m in view["missing_tail"]] == ["Gereç ve yöntem"]


def test_missing_section_number_follows_its_place() -> None:
    blocks = [heading("ÖZET"), para(), heading("GİRİŞ"), para()]
    view = report_view(report([finding("a.x", block=3), finding("b.x", block=1),
                               missing("SUMMARY")], blocks), REQUIRED)
    assert [c["rule_id"] for c in view["cards"]] == ["b.x", "document.missing_section", "a.x"]


@pytest.mark.parametrize(("name", "label"), [
    ("ÖNSÖZ", "Önsöz"), ("İÇİNDEKİLER", "İçindekiler"), ("SUMMARY", "Summary"),
    ("GEREÇ VE YÖNTEM", "Gereç ve yöntem"), ("ISI", "Isı"),
])
def test_section_label_uses_turkish_case(name: str, label: str) -> None:
    assert _section_label(name) == label


def test_placeholder_is_rendered_and_linked(client: TestClient) -> None:
    html = client.get("/demo").text
    if "document.missing_section" in html or "Eksik:" in html:
        assert 'class="blk blk-missing' in html
        assert 'id="bm0"' in html and 'data-jump="m0"' in html


# --- B7, B8, B9, B12-B19 --------------------------------------------------------------------------


def test_more_badge_is_a_labelled_button_that_filters(client: TestClient) -> None:
    html = client.get("/demo").text
    more = re.search(r'<button type="button" class="pin more"[^>]*>', html)
    if more:
        assert "data-only-cards=" in more.group(0)
        assert re.search(r'aria-label="Bu satırda \d+ bulgu daha var', more.group(0))
        assert 'title="Bu satırda' in more.group(0)
    assert "data-only-cards" in JS


def test_blocks_are_not_nested_buttons(client: TestClient) -> None:
    assert 'role="button"' not in client.get("/demo").text.split('class="paper"')[1]


def test_highlighted_block_has_short_summary(client: TestClient, mailer: ConsoleMailer) -> None:
    html = done_page(client, mailer, bad_thesis())
    assert re.search(r'<span class="blk-note" title="[^"]+"><b>Hata:</b> ', html)


def test_card_selects_from_either_side_and_clears_filter() -> None:
    assert "scrollInto(canvas, blocks[0])" in JS
    assert "showAll()" in JS.split("const openCard")[1].split("};")[0]


def test_download_buttons_name_what_they_do(client: TestClient, mailer: ConsoleMailer) -> None:
    html = done_page(client, mailer, bad_thesis())
    assert "Yorumlu kopyayı indir (tüm bulgular)" in html
    assert "1 bulguyu düzelten kopyayı indir" in html
    bar = html.split('class="toolbar-right"')[1].split('id="output-panel"')[0]
    assert 'class="arr dl"' in bar and "M4 12" not in bar


def test_ruleset_name_is_complete_for_hover_and_focus(client: TestClient) -> None:
    html = client.get("/demo").text
    match = re.search(r'class="doc-ruleset" tabindex="0" title="([^"]+)">([^<]+)<', html)
    assert match and match.group(1) == match.group(2)


def test_text_view_box_is_optional_and_dismissable(client: TestClient,
                                                   mailer: ConsoleMailer) -> None:
    html = done_page(client, mailer, bad_thesis())
    box = html.split('id="docview"')[1].split('id="docview-status"')[0]
    assert "İsterseniz metninizi de görün (isteğe bağlı)" in box
    assert "paragraflar çizgiyle gösterilir" in box
    assert 'data-docview-dismiss aria-label="Bu bilgiyi kapat"' in box
    assert 'id="docview-open"' in box and "btn small primary" not in box
    assert "çizgiyle gösterilir" not in html.split('class="canvas-legend"')[1].split("</div>")[0]
    assert "localStorage" in JS and "sontez.docview.dismissed" in JS


def test_next_steps_are_open_by_default(client: TestClient, mailer: ConsoleMailer) -> None:
    assert '<details class="next" open>' in done_page(client, mailer, bad_thesis())


def test_cover_note_is_a_warning_in_plain_words() -> None:
    template = (STATIC.parent / "templates" / "job.html").read_text(encoding="utf-8")
    assert '<p class="notice-warn"><strong>Denetlenmedi:</strong>' in template
    assert "{{ s.cover_paragraphs }} paragraf" in template
    assert "satır) denetlenmedi" not in template


def test_status_label_sits_beside_the_number(client: TestClient, mailer: ConsoleMailer) -> None:
    html = done_page(client, mailer, bad_thesis())
    head = html.split('class="comment-head"')[1].split("</div>")[0]
    assert 'class="pin"' in head and 'class="sev-label error"' in head and ">Hata<" in head


def test_stepper_is_labelled_for_findings(client: TestClient, mailer: ConsoleMailer) -> None:
    html = done_page(client, mailer, bad_thesis())
    assert 'aria-label="Önceki bulgu" title="Önceki bulgu (K)"' in html
    assert 'aria-label="Sonraki bulgu" title="Sonraki bulgu (J)"' in html
    assert 'e.key === "j"' in JS and 'closest(".workspace")' in JS


def test_suggest_moves_to_outline_where_it_can_cover_cards(client: TestClient) -> None:
    html = client.get("/demo").text
    outline = html.split('class="pane pane-outline"')[1].split("</nav>")[0]
    assert "data-open-suggest" in outline and "İstek / Öneri" in outline
    assert "[data-open-suggest]" in JS
    rule = re.search(r"@media \(min-width: 1000px\) and \(min-height: 501px\) \{(.*?)\n\}",
                     CSS, re.S)
    assert rule and "body.editor .suggest-fab { display: none; }" in rule.group(1)


def test_empty_report_says_zero_findings() -> None:
    template = (STATIC.parent / "templates" / "job.html").read_text(encoding="utf-8")
    assert '<p class="empty-count">0 bulgu</p>' in template
    assert "Bu süzgeçte bulgu yok." in template and "data-filter-reset" in template


# --- A: görsel kimlik ve B21 ----------------------------------------------------------------------


def report_css() -> str:
    match = re.search(r"/\* == RAPOR == \*/(.*?)/\* == /RAPOR == \*/", CSS, re.S)
    assert match, "RAPOR bloğu yok"
    return match.group(1)


def test_shared_classes_are_not_restyled_for_other_pages() -> None:
    """Başka sayfaların da kullandığı sınıflar rapor kuralından etkilenmez."""
    block = report_css()
    assert not re.search(r"^\.fineprint \{", block, re.M)
    assert not re.search(r"^\.tag \{", block, re.M)
    assert ".fineprint { font-size: .74rem; color: var(--muted); }" in CSS


def test_report_css_uses_only_tokens() -> None:
    block = report_css()
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", block)
    assert not re.search(r"\brgba?\(", block)


def test_report_css_drops_template_look() -> None:
    block = report_css()
    assert "gradient" not in block
    assert "text-transform: uppercase" not in block
    assert "var(--mono)" not in block
    assert "border-top: 3px" not in block
    assert "tabular-nums" in block
    # Gölge yalnızca yüzen öğede: kopya penceresi.
    shadows = re.findall(r"([^{}\n]+)\{[^}]*box-shadow: (?!none|inset)[^}]*\}", block)
    assert [s.strip() for s in shadows] == [".output-panel"]


def test_report_radius_is_modest_except_filters() -> None:
    assert re.search(r"--rp-radius: 5px;", CSS) and re.search(r"--rp-radius-s: 4px;", CSS)
    block = report_css()
    allowed = {".filters", ".filters button", ".pin", ".comment .tag"}
    for selector, _ in re.findall(r"([^{}\n]+)\{[^}]*(border-radius: var\(--radius-pill\))", block):
        assert selector.strip() in allowed, selector


def test_status_colors_are_not_the_only_signal(client: TestClient, mailer: ConsoleMailer) -> None:
    html = done_page(client, mailer, bad_thesis())
    assert '<span class="lg lg-error">Hata</span>' in html
    assert "<b>Hata:</b>" in html  # belgede de yazıyla
    assert re.search(r'class="pin" data-open-card="\d+" aria-label="[^"]*Yorum \d+, Hata', html)
