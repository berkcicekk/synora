"""İstek/öneri kutusu (popup): POST /oneri.

Girişsiz de çalışır; CSRF yerine özel başlık zorunludur (siteler arası klasik form
özel başlık koyamaz), girişliyse oturum CSRF'si de aranır. Bal küpü ve hız sınırı var.
Tez metniyle ilgisi yok: yalnızca kullanıcının gönüllü yazdığı mesaj saklanır.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from test_web import login

from synora.web.db import Database
from synora.web.mailer import ConsoleMailer

HEADERS = {"X-Requested-With": "fetch"}


def rows(client: TestClient) -> list[tuple]:
    db: Database = client.app.state.db  # type: ignore[attr-defined]
    return db.execute("SELECT message, email, page FROM suggestions ORDER BY id").fetchall()


def test_anonymous_suggestion_is_stored(client: TestClient) -> None:
    res = client.post("/oneri", data={"message": "  Koyu  tema olsun ", "page": "/demo"},
                      headers=HEADERS)
    assert res.status_code == 200 and res.json() == {"ok": True}
    assert rows(client) == [("Koyu tema olsun", "", "/demo")]


def test_fetch_header_is_required_against_csrf(client: TestClient) -> None:
    assert client.post("/oneri", data={"message": "selam"}).status_code == 403
    assert rows(client) == []


def test_empty_long_or_bad_email_is_rejected(client: TestClient) -> None:
    assert client.post("/oneri", data={"message": "   "}, headers=HEADERS).status_code == 400
    assert client.post("/oneri", data={"message": "a" * 2001},
                       headers=HEADERS).status_code == 400
    assert client.post("/oneri", data={"message": "selam", "email": "ben"},
                       headers=HEADERS).status_code == 400
    assert rows(client) == []


def test_honeypot_pretends_success_but_stores_nothing(client: TestClient) -> None:
    res = client.post("/oneri", data={"message": "spam", "website": "http://spam"},
                      headers=HEADERS)
    assert res.status_code == 200 and rows(client) == []


def test_bad_page_value_is_dropped(client: TestClient) -> None:
    res = client.post("/oneri", data={"message": "selam", "page": "javascript:x"},
                      headers=HEADERS)
    assert res.status_code == 200 and rows(client)[0][2] == ""


def test_logged_in_user_email_is_attached(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    res = client.post("/oneri", data={"message": "tablo denetimi istiyorum"},
                      headers={**HEADERS, "X-CSRF-Token": csrf})
    assert res.status_code == 200
    assert rows(client) == [("tablo denetimi istiyorum", "ogrenci@beun.edu.tr", "")]
    # Oturum açıkken CSRF başlığı olmayan istek reddedilir.
    assert client.post("/oneri", data={"message": "x"}, headers=HEADERS).status_code == 403


def test_rate_limit_per_client(client: TestClient) -> None:
    for i in range(5):
        assert client.post("/oneri", data={"message": f"öneri {i}"},
                           headers=HEADERS).status_code == 200
    assert client.post("/oneri", data={"message": "altıncı"},
                       headers=HEADERS).status_code == 429
    assert len(rows(client)) == 5


def test_popup_markup_is_on_every_page(client: TestClient) -> None:
    for path in ("/", "/fiyatlandirma", "/giris"):
        page = client.get(path).text
        assert 'id="suggest-dialog"' in page and 'id="suggest-open"' in page, path
