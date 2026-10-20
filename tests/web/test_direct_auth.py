"""Doğrulamasız giriş/kayıt (SYNORA_EMAIL_VERIFICATION=0) ve sonek alan adı kuralı.

Demo kipinde e-postaya bağlantı gönderilmez: kayıt formu e-postayı ve aydınlatma onayını
alır, kullanıcı satırı (whitelist) açılır ve oturum hemen başlar. Giriş yalnızca kayıtlı
e-postalarla olur. `.edu.tr` gibi nokta ile başlayan alan adı girdisi sonek kuralıdır.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_web import csrf_from

from synora.web.app import SESSION_COOKIE, TERMS_VERSION, create_app
from synora.web.db import Database
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
EMAIL = "ogrenci@beun.edu.tr"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "t.db", rulesets_dir=ROOT / "rulesets", base_url="http://testserver",
        allowed_domains=(".edu.tr",), dev=True, isolate_jobs=False, workers=1,
        email_verification=False,
    )


@pytest.fixture
def mailer() -> ConsoleMailer:
    return ConsoleMailer(echo=False)


@pytest.fixture
def client(settings: Settings, mailer: ConsoleMailer) -> Iterator[TestClient]:
    with TestClient(create_app(settings, mailer)) as c:
        yield c


def register(client: TestClient, email: str = EMAIL, kvkk: bool = True):
    page = client.get("/kayit")
    data = {"email": email, "csrf": csrf_from(page.text)}
    if kvkk:
        data["kvkk"] = "1"
    return client.post("/kayit", data=data, follow_redirects=False)


def login(client: TestClient, email: str = EMAIL):
    page = client.get("/giris")
    return client.post("/login", data={"email": email, "csrf": csrf_from(page.text)},
                       follow_redirects=False)


def test_register_opens_session_without_email(client: TestClient, mailer: ConsoleMailer) -> None:
    res = register(client)
    assert res.status_code == 303
    assert res.cookies.get(SESSION_COOKIE)
    assert mailer.sent == []  # hiç e-posta gönderilmez
    db: Database = client.app.state.db  # type: ignore[attr-defined]
    got = db.user_consent(EMAIL)
    assert got is not None and got[0] == TERMS_VERSION  # whitelist + onay kaydı


def test_register_without_consent_is_rejected(client: TestClient) -> None:
    res = register(client, kvkk=False)
    assert res.status_code == 400
    assert res.cookies.get(SESSION_COOKIE) is None


def test_login_requires_prior_registration(client: TestClient) -> None:
    res = login(client)
    assert res.status_code == 400
    assert "kay" in res.text.lower()  # kullanıcı kayda yönlendirilir


def test_registered_user_can_log_back_in(client: TestClient) -> None:
    assert register(client).status_code == 303
    client.cookies.clear()
    res = login(client)
    assert res.status_code == 303
    assert res.cookies.get(SESSION_COOKIE)


def test_suffix_domain_rule(client: TestClient) -> None:
    # ".edu.tr" her alt alan adını kabul eder, başka uzantıları etmez.
    assert register(client, email="x@ogrenci.itu.edu.tr").status_code == 303
    client.cookies.clear()
    assert register(client, email="x@gmail.com").status_code == 400
    assert register(client, email="x@kotuedu.tr").status_code == 400


def test_exact_domains_still_exact(tmp_path: Path, mailer: ConsoleMailer) -> None:
    s = Settings(db_path=tmp_path / "e.db", rulesets_dir=ROOT / "rulesets",
                 base_url="http://testserver", allowed_domains=("beun.edu.tr",), dev=True,
                 isolate_jobs=False, workers=1, email_verification=False)
    with TestClient(create_app(s, mailer)) as c:
        assert register(c, email="x@ogrenci.beun.edu.tr").status_code == 400
        assert register(c, email="x@beun.edu.tr").status_code == 303


def test_production_without_smtp_is_fine_when_verification_off(tmp_path: Path) -> None:
    s = Settings(db_path=tmp_path / "p.db", rulesets_dir=ROOT / "rulesets",
                 base_url="https://demo.payper.live", allowed_domains=(".edu.tr",),
                 dev=False, email_verification=False)
    assert s.problems() == []


def test_production_with_verification_still_requires_smtp(tmp_path: Path) -> None:
    s = Settings(db_path=tmp_path / "p.db", rulesets_dir=ROOT / "rulesets",
                 base_url="https://demo.payper.live", allowed_domains=(".edu.tr",), dev=False)
    assert any("SMTP" in p for p in s.problems())
