"""Üretimde (dev=False) güvensiz ya da eksik ayarla uygulama başlamaz; e-posta konsola düşmez."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from synora.cli import app as cli
from synora.web.app import create_app
from synora.web.mailer import ConsoleMailer, SmtpMailer, make_mailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def prod(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "p.db", rulesets_dir=ROOT / "rulesets",
                    base_url="https://synora.example.edu.tr", allowed_domains=("beun.edu.tr",),
                    dev=False, isolate_jobs=False, workers=1, smtp_host="smtp.example.edu.tr",
                    smtp_from="Synora <synora@example.edu.tr>")


def test_complete_production_settings_have_no_problems(prod: Settings) -> None:
    assert prod.problems() == []
    assert isinstance(make_mailer(prod), SmtpMailer)


@pytest.mark.parametrize(("change", "word"), [
    ({"base_url": "http://synora.example.edu.tr"}, "https"),
    ({"smtp_host": ""}, "SMTP_HOST"),
    ({"smtp_from": "Synora <noreply@synora.local>"}, "SMTP_FROM"),
    ({"allowed_domains": ()}, "ALLOWED_DOMAINS"),
    ({"default_ruleset": "boyle-bir-kilavuz-yok"}, "DEFAULT_RULESET"),
])
def test_each_unsafe_setting_is_reported(prod: Settings, change: dict[str, object],
                                         word: str) -> None:
    problems = replace(prod, **change).problems()  # type: ignore[arg-type]
    assert any(word in p for p in problems), problems


def test_app_refuses_to_start_with_unsafe_production_settings(prod: Settings) -> None:
    with pytest.raises(RuntimeError, match="https"):
        create_app(replace(prod, base_url="http://synora.example.edu.tr"), ConsoleMailer())


def test_missing_rulesets_dir_is_reported(prod: Settings, tmp_path: Path) -> None:
    problems = replace(prod, rulesets_dir=tmp_path / "yok").problems()
    assert any("DEFAULT_RULESET" in p for p in problems)


def test_production_mailer_never_falls_back_to_console(prod: Settings) -> None:
    # Eskiden SMTP_HOST boşsa bağlantı (canlı giriş anahtarı) sunucu kaydına yazılıyordu.
    with pytest.raises(RuntimeError, match="SMTP_HOST"):
        make_mailer(replace(prod, smtp_host=""))
    assert isinstance(make_mailer(replace(prod, dev=True, smtp_host="")), ConsoleMailer)


def test_dev_settings_skip_production_checks(prod: Settings) -> None:
    assert replace(prod, dev=True, base_url="http://127.0.0.1:8765", smtp_host="").problems() == []


def test_serve_refuses_stray_dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sunucuda unutulmuş SYNORA_DEV=1 bağlantıları konsola yazar ve çerezleri Secure yapmaz.
    monkeypatch.setenv("SYNORA_DEV", "1")
    result = CliRunner().invoke(cli, ["serve"])
    assert result.exit_code == 2
    assert "SYNORA_DEV" in result.output
