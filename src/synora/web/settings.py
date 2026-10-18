"""Web ayarları. Tümü ortam değişkenlerinden (SYNORA_*) okunur."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _env(name: str, default: str) -> str:
    return os.environ.get(f"SYNORA_{name}", default)


@dataclass(frozen=True)
class Settings:
    db_path: Path = ROOT / "var" / "synora.db"
    rulesets_dir: Path = ROOT / "rulesets"
    # Yükleme ekranında seçili gelen ve giriş sayfasında tanıtılan kılavuz
    default_ruleset: str = "zbeu-tip"
    base_url: str = "http://127.0.0.1:8000"
    # Yalnızca bu alan adlarındaki e-postalar giriş yapabilir. Boş = herkes (yalnızca dev).
    allowed_domains: tuple[str, ...] = ("beun.edu.tr", "ogrenci.beun.edu.tr")
    dev: bool = False  # e-posta yerine bağlantıyı konsola yaz, çerezler Secure değil
    retention_hours: float = 24.0
    session_hours: float = 12.0
    login_token_minutes: float = 15.0
    login_requests_per_hour: int = 5
    max_active_jobs: int = 2
    max_daily_jobs: int = 20
    max_upload_bytes: int = 50 * 1024 * 1024
    job_timeout_seconds: float = 120.0
    workers: int = 2
    isolate_jobs: bool = True  # her iş ayrı süreçte (testlerde kapatılabilir)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = field(default="", repr=False)
    smtp_from: str = "Synora <noreply@synora.local>"

    @property
    def secure_cookies(self) -> bool:
        return not self.dev

    def problems(self) -> list[str]:
        """Üretimde (dev=False) başlamayı engelleyen eksik ya da güvensiz ayarlar."""
        if self.dev:
            return []
        found = []
        if not self.base_url.startswith("https://"):
            found.append("SYNORA_BASE_URL https:// ile başlamalı (Secure çerezler ve "
                         "giriş bağlantıları için)")
        if not self.smtp_host:
            found.append("SYNORA_SMTP_HOST boş: giriş bağlantıları gönderilemez")
        if self.smtp_from.endswith(".local>") or self.smtp_from.endswith(".local"):
            found.append("SYNORA_SMTP_FROM gerçek bir gönderici adresi olmalı")
        if not self.allowed_domains:
            found.append("SYNORA_ALLOWED_DOMAINS boş: herkes giriş yapabilirdi")
        if not (self.rulesets_dir / f"{self.default_ruleset}.yaml").is_file():
            found.append(f"SYNORA_DEFAULT_RULESET bulunamadı: {self.default_ruleset} "
                         f"({self.rulesets_dir})")
        return found

    @classmethod
    def from_env(cls) -> Settings:
        raw_domains = _env("ALLOWED_DOMAINS", "").split(",")
        domains = tuple(d.strip().lower() for d in raw_domains if d.strip())
        return cls(
            db_path=Path(_env("DB_PATH", str(cls.db_path))),
            rulesets_dir=Path(_env("RULESETS_DIR", str(cls.rulesets_dir))),
            default_ruleset=_env("DEFAULT_RULESET", cls.default_ruleset),
            base_url=_env("BASE_URL", cls.base_url).rstrip("/"),
            allowed_domains=domains or cls.allowed_domains,
            dev=_env("DEV", "0") == "1",
            retention_hours=float(_env("RETENTION_HOURS", str(cls.retention_hours))),
            workers=int(_env("WORKERS", str(cls.workers))),
            smtp_host=_env("SMTP_HOST", ""),
            smtp_port=int(_env("SMTP_PORT", "587")),
            smtp_user=_env("SMTP_USER", ""),
            smtp_password=_env("SMTP_PASSWORD", ""),
            smtp_from=_env("SMTP_FROM", cls.smtp_from),
        )
