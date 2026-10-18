"""Giriş e-postası: SMTP hatası 500 değil anlaşılır mesaj; sunucu kilitlenmez; başlıklar."""

from __future__ import annotations

import smtplib
from dataclasses import replace
from email.message import EmailMessage
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from test_web import csrf_from

from synora.web.app import create_app
from synora.web.mailer import SmtpMailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


class FailingMailer:
    def __init__(self) -> None:
        self.calls = 0

    def send_login_link(self, email: str, link: str) -> None:
        self.calls += 1
        raise smtplib.SMTPServerDisconnected("bağlantı koptu")


def test_smtp_failure_shows_friendly_message_and_does_not_count(settings: Settings) -> None:
    mailer = FailingMailer()
    with TestClient(create_app(settings, mailer)) as client:  # type: ignore[arg-type]
        for _ in range(settings.login_requests_per_hour + 1):
            page = client.get("/giris")
            res = client.post("/login", data={"email": "a@beun.edu.tr",
                                              "csrf": csrf_from(page.text)})
            assert res.status_code == 503
            assert "E-posta gönderilemedi" in res.text
            assert 'value="a@beun.edu.tr"' in res.text
        # Gönderilemeyen bağlantılar saatlik sınırdan düşmez: öğrenci yeniden deneyebilir.
        assert mailer.calls == settings.login_requests_per_hour + 1


class FakeSMTP:
    instances: ClassVar[list[FakeSMTP]] = []

    def __init__(self, host: str, port: int, timeout: float, **kw: Any) -> None:
        self.host, self.port, self.kw = host, port, kw
        self.tls = False
        self.sent: list[EmailMessage] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self, context: object) -> None:
        self.tls = True

    def login(self, user: str, password: str) -> None:
        pass

    def send_message(self, msg: EmailMessage) -> None:
        self.sent.append(msg)


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", type("FakeSSL", (FakeSMTP,), {}))
    return FakeSMTP


def _prod(settings: Settings, **kw: Any) -> Settings:
    return replace(settings, dev=False, smtp_host="smtp.example.edu.tr",
                   smtp_from="Synora <synora@example.edu.tr>", **kw)


def test_smtp_message_has_date_and_message_id(settings: Settings,
                                              fake_smtp: type[FakeSMTP]) -> None:
    SmtpMailer(_prod(settings)).send_login_link("a@beun.edu.tr", "https://x/auth?token=t")
    smtp = fake_smtp.instances[-1]
    assert smtp.tls and type(smtp).__name__ == "FakeSMTP"
    msg = smtp.sent[-1]
    assert msg["Date"] and msg["Message-ID"]
    assert msg["To"] == "a@beun.edu.tr"


def test_port_465_uses_implicit_tls(settings: Settings, fake_smtp: type[FakeSMTP]) -> None:
    SmtpMailer(_prod(settings, smtp_port=465)).send_login_link("a@beun.edu.tr", "https://x")
    smtp = fake_smtp.instances[-1]
    assert type(smtp).__name__ == "FakeSSL" and not smtp.tls
