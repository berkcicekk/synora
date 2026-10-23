"""Girişsiz örnek rapor (/demo): pakete gömülü sentetik tez, varsayılan kural setiyle.

Rapor gerçektir ama belge sentetiktir; rol düzenleme, kopya üretimi ve silme kapalıdır.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_demo_report_without_login(client: TestClient) -> None:
    res = client.get("/demo")
    assert res.status_code == 200
    html = res.text
    assert "Örnek rapor · sentetik tez" in html
    assert "hata" in html.lower()
    assert "Kendi tezinizle deneyin" in html


def test_demo_disables_outputs_roles_and_delete(client: TestClient) -> None:
    html = client.get("/demo").text
    assert 'id="outputs"' not in html  # kopya üretim JS'i devreye girmez
    assert "data-output=" not in html
    assert "Raporu şimdi sil" not in html
    assert "report.json" not in html
    assert "role-pick" not in html  # rol düzenleme kapalı
    assert "kendiliğinden silinir" not in html


def test_demo_is_cached_and_deterministic(client: TestClient) -> None:
    first = client.get("/demo").text
    second = client.get("/demo").text
    # Zaman damgası dışındaki içerik aynı; özet satırı birebir eşleşmeli.
    assert first.split("tally")[1][:120] == second.split("tally")[1][:120]


def test_landing_links_to_demo(client: TestClient) -> None:
    assert 'href="/demo"' in client.get("/").text


def test_demo_shows_checked_rules(client: TestClient) -> None:
    html = client.get("/demo").text
    assert "Denetlendi ve uygun:" in html
