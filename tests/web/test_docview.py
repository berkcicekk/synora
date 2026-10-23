"""Rapor sayfasında tezin metni: dosya yalnızca öğrencinin tarayıcısında açılır.

Sunucu metni hiç görmez ve rapora koymaz; sayfa yalnızca blokların gövde paragraf sırasını
(sayı) ve yüklenen dosyanın SHA-256 özetini taşır. Görüntüleyici betiği ağ ya da tarayıcı
deposu kullanmaz; tek istisna örnek rapordaki sentetik tezin indirilmesidir.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi.testclient import TestClient
from test_web import SECRET, bad_thesis, login, upload, wait_done

from synora.web.mailer import ConsoleMailer

STATIC = Path(__file__).resolve().parents[2] / "src" / "synora" / "web" / "static"


def _report_html(client: TestClient, mailer: ConsoleMailer, data: bytes) -> str:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, data)
    assert wait_done(client, job_id) == "done"
    return client.get(f"/jobs/{job_id}").text


def test_report_page_offers_local_viewer_without_text(client: TestClient,
                                                      mailer: ConsoleMailer) -> None:
    data = bad_thesis()
    html = _report_html(client, mailer, data)
    assert 'id="docview"' in html
    assert f'data-sha="{hashlib.sha256(data).hexdigest()}"' in html
    assert "data-sample" not in html  # öğrencinin kendi dosyası; örnek indirilmez
    assert "sunucuya gönderilmez" in html
    assert re.search(r'class="blk blk-para[^"]*"[^>]*data-i="\d+"', html)
    assert '/static/docview.js?v=' in html
    assert SECRET not in html  # metin sayfada yok; yalnızca tarayıcıda dosyadan okunur


def test_demo_viewer_loads_the_synthetic_sample(client: TestClient) -> None:
    html = client.get("/demo").text
    assert 'data-sample="/static/ornek-tez.docx"' in html
    assert "data-sha" not in html
    assert client.get("/static/ornek-tez.docx").status_code == 200


def test_viewer_script_never_sends_or_stores_the_file() -> None:
    js = (STATIC / "docview.js").read_text(encoding="utf-8")
    for banned in ("XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "localStorage",
                   "sessionStorage", "indexedDB", "caches.", "postMessage", "innerHTML",
                   "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert banned not in js, banned
    # Tek ağ isteği: örnek rapordaki sentetik tezin GET ile alınması.
    fetches = [line for line in js.splitlines() if "fetch(" in line]
    assert len(fetches) == 1 and "sample" in fetches[0]
    assert "POST" not in js and "body:" not in js


def test_viewer_script_is_cache_busted() -> None:
    from synora.web import app as web_app

    src = Path(web_app.__file__).read_text(encoding="utf-8")
    assert '"docview.js"' in src
