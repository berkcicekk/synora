"""Giriş bağlantısı gönderimi. Geliştirmede konsola yazar, üretimde SMTP kullanır."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Protocol

from synora.web.settings import Settings


class Mailer(Protocol):
    def send_login_link(self, email: str, link: str) -> None: ...


class ConsoleMailer:
    """Yalnızca geliştirme ve test içindir: bağlantıyı bellekte tutar ve konsola yazar."""

    def __init__(self, echo: bool = True) -> None:
        self.sent: list[tuple[str, str]] = []
        self.echo = echo

    def send_login_link(self, email: str, link: str) -> None:
        self.sent.append((email, link))
        if self.echo:
            print(f"[synora dev] Giriş bağlantısı ({email}): {link}", flush=True)


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def send_login_link(self, email: str, link: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.s.smtp_from
        msg["To"] = email
        msg["Subject"] = "Synora giriş bağlantınız"
        msg.set_content(
            "Merhaba,\n\nSynora'ya giriş yapmak için aşağıdaki bağlantıyı açın. "
            "Bağlantı 15 dakika geçerlidir ve yalnızca bir kez kullanılabilir.\n\n"
            f"{link}\n\nBu isteği siz yapmadıysanız bu e-postayı yok sayabilirsiniz.\n"
        )
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.s.smtp_from.rsplit("@", 1)[-1].strip("> "))
        context = ssl.create_default_context()
        if self.s.smtp_port == 465:  # örtük TLS (SMTPS)
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(self.s.smtp_host, self.s.smtp_port,
                                                  timeout=20, context=context)
        else:
            smtp = smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=20)
        with smtp:
            if self.s.smtp_port != 465:
                smtp.starttls(context=context)
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
            smtp.send_message(msg)


def make_mailer(settings: Settings) -> Mailer:
    if settings.dev:
        return ConsoleMailer()
    if not settings.smtp_host:
        # Konsola düşmek canlı giriş bağlantısını sunucu kaydına yazardı.
        raise RuntimeError("SYNORA_SMTP_HOST tanımlı değil: üretimde e-posta gönderilemez")
    return SmtpMailer(settings)
