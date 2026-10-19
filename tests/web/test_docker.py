"""Docker kurulumu systemd kurulumunun güvencelerini korur: kök olmayan kullanıcı, yalnızca yerel
port, salt okunur dosya sistemi, tek örnek, derleme bağlamına yalnızca gereken dosyalar."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return (ROOT / "Dockerfile").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def service() -> dict[str, object]:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert list(compose["services"]) == ["synora"]
    return compose["services"]["synora"]  # type: ignore[no-any-return]


def _final_stage(dockerfile: str) -> str:
    return dockerfile.rsplit("\nFROM ", 1)[1]


def test_build_context_is_an_allowlist() -> None:
    # Gerçek tezler (tests/fixtures/real), yerel veritabanı (var/), ayar dosyaları imaja girmesin.
    lines = [line.strip() for line in (ROOT / ".dockerignore").read_text(encoding="utf-8")
             .splitlines() if line.strip() and not line.startswith("#")]
    assert lines[0] == "*"
    assert sorted(lines[1:]) == ["!pyproject.toml", "!rulesets", "!src", "!uv.lock"]


def test_image_runs_as_non_root_without_dev(dockerfile: str) -> None:
    final = _final_stage(dockerfile)
    assert "\nUSER synora" in final
    assert "\nVOLUME /data" in final  # veritabanı kapsayıcı katmanına yazılmaz
    assert "--dev" not in dockerfile and "SYNORA_DEV=1" not in dockerfile
    assert 'CMD ["synora", "serve", "--host", "0.0.0.0", "--port", "8000"]' in final


def test_image_healthcheck_uses_health_endpoint(dockerfile: str) -> None:
    final = _final_stage(dockerfile)
    assert "HEALTHCHECK" in final and "http://127.0.0.1:8000/health" in final


def test_image_tools_are_pinned(dockerfile: str) -> None:
    for line in dockerfile.splitlines():
        if line.startswith(("FROM ", "COPY --from=ghcr")):
            image = line.split()[1].removeprefix("--from=")
            assert ":" in image and not image.endswith((":latest", ":3")), line


def test_port_is_published_only_on_localhost(service: dict[str, object]) -> None:
    # Önde nginx (deploy/nginx-synora.conf) TLS'i sonlandırır; uygulama dışarıya açılmaz.
    assert service["ports"] == ["127.0.0.1:8000:8000"]


def test_container_is_hardened(service: dict[str, object]) -> None:
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]  # type: ignore[operator]
    assert service["init"] is True  # her iş için açılan alt süreçler toplanır
    assert service["mem_limit"] and service["pids_limit"]
    assert any(str(t).startswith("/tmp:") for t in service["tmpfs"])  # type: ignore[attr-defined]


def test_single_instance_with_persistent_database(service: dict[str, object]) -> None:
    # İki örnek aynı veritabanında birbirinin işlerini "yarıda kaldı" sayar.
    assert "deploy" not in service and "scale" not in service
    assert "synora-data:/data" in service["volumes"]  # type: ignore[operator]
    assert service["env_file"] == ["/etc/synora/synora.env"]


def test_compose_overrides_paths_known_to_settings(service: dict[str, object],
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    env: dict[str, str] = service["environment"]  # type: ignore[assignment]
    assert env["SYNORA_DEV"] == "0"
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    assert settings.db_path == Path("/data/synora.db")
    assert settings.rulesets_dir == Path("/app/rulesets")
    assert not settings.dev
