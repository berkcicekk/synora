"""Yönetim paneli + Cloudflare Access: kimliği uygulama da doğrular (JWT), Access'e körü körüne
güvenmez. Access ayarlıysa anahtar yöntemi tamamen kapalıdır; yetkisiz herkes 404 görür.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from test_web import login

from synora.web import access as access_module
from synora.web.access import AccessVerifier
from synora.web.app import create_app
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ADMIN = "yonetici@beun.edu.tr"
KEY = "dogru-anahtar-0123456789abcdef"
TEAM = "sontez-test.cloudflareaccess.com"
AUD = "a" * 64
PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk(private: rsa.RSAPrivateKey = PRIVATE, kid: str = "k1") -> dict[str, Any]:
    return {**RSAAlgorithm.to_jwk(private.public_key(), as_dict=True), "kid": kid}


def mint(private: rsa.RSAPrivateKey = PRIVATE, kid: str = "k1", **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {"aud": [AUD], "iss": f"https://{TEAM}", "email": ADMIN,
                              "sub": "kullanici", "iat": now, "exp": now + 600}
    claims.update(overrides)
    payload = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(payload, private, algorithm="RS256", headers={"kid": kid})


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def forged(alg: str, signature: bytes = b"") -> str:
    now = int(time.time())
    head = _b64(json.dumps({"alg": alg, "typ": "JWT", "kid": "k1"}).encode())
    body = _b64(json.dumps({"aud": [AUD], "iss": f"https://{TEAM}", "email": ADMIN,
                            "exp": now + 600}).encode())
    if alg == "HS256":  # açık anahtarı HMAC sırrı gibi kullanma (algoritma karışıklığı)
        pem = PRIVATE.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        signature = hmac.new(pem, f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(signature)}"


@pytest.fixture
def jwks_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake(team: str) -> dict[str, Any]:
        calls.append(team)
        return {"keys": [jwk()]}

    monkeypatch.setattr(access_module, "fetch_jwks", fake)
    return calls


@pytest.fixture
def access_client(settings: Settings, mailer: ConsoleMailer,
                  jwks_calls: list[str]) -> Iterator[TestClient]:
    configured = replace(settings, admin_emails=(ADMIN,),
                         admin_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
                         access_team_domain=TEAM, access_aud=AUD)
    with TestClient(create_app(configured, mailer)) as c:
        yield c


def page(client: TestClient, token: str | None) -> Any:
    headers = {} if token is None else {"Cf-Access-Jwt-Assertion": token}
    return client.get("/yonetim", headers=headers)


# --- Geçerli kimlik ---------------------------------------------------------------------------


def test_valid_token_opens_panel_without_session_or_key(access_client: TestClient) -> None:
    res = page(access_client, mint())
    assert res.status_code == 200 and "Kayıtlı hesap" in res.text
    assert res.headers["cache-control"] == "no-store"
    assert "/cdn-cgi/access/logout" in res.text  # çıkış Access oturumunu kapatır


def test_email_claim_is_compared_case_insensitively(access_client: TestClient) -> None:
    assert page(access_client, mint(email="Yonetici@Beun.edu.tr")).status_code == 200


# --- Reddedilenler: hepsi 404 ------------------------------------------------------------------


@pytest.mark.parametrize("token", [
    None,
    "",
    "cop",
    "a.b.c",
    "x" * 9000,
])
def test_missing_or_garbage_token_gets_404(access_client: TestClient, token: str | None) -> None:
    assert page(access_client, token).status_code == 404


@pytest.mark.parametrize("overrides", [
    {"aud": ["b" * 64]},
    {"aud": None},
    {"iss": "https://baska.cloudflareaccess.com"},
    {"iss": None},
    {"exp": int(time.time()) - 3600},
    {"exp": None},
    {"nbf": int(time.time()) + 3600},
    {"email": "ogrenci@beun.edu.tr"},
    {"email": None, "common_name": "servis-jetonu"},
    {"email": 12345},
])
def test_bad_claims_get_404(access_client: TestClient, overrides: dict[str, Any]) -> None:
    assert page(access_client, mint(**overrides)).status_code == 404


def test_token_signed_by_another_key_gets_404(access_client: TestClient) -> None:
    assert page(access_client, mint(OTHER_PRIVATE)).status_code == 404


@pytest.mark.parametrize("alg", ["none", "HS256"])
def test_algorithm_downgrade_gets_404(access_client: TestClient, alg: str) -> None:
    assert page(access_client, forged(alg)).status_code == 404


def test_unknown_kid_gets_404(access_client: TestClient) -> None:
    assert page(access_client, mint(kid="bilinmeyen")).status_code == 404


def test_unreachable_keys_fail_closed(settings: Settings, mailer: ConsoleMailer,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    def down(team: str) -> dict[str, Any]:
        raise OSError("ulasilamadi")

    monkeypatch.setattr(access_module, "fetch_jwks", down)
    configured = replace(settings, admin_emails=(ADMIN,), access_team_domain=TEAM, access_aud=AUD)
    with TestClient(create_app(configured, mailer)) as c:
        assert page(c, mint()).status_code == 404


# --- Anahtar yöntemine dönüş yok ---------------------------------------------------------------


def test_key_route_and_session_do_not_open_panel_in_access_mode(
        access_client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(access_client, mailer, ADMIN)
    res = access_client.post("/yonetim/anahtar", data={"key": KEY, "csrf": csrf},
                             follow_redirects=False)
    assert res.status_code == 404
    assert access_client.get("/yonetim").status_code == 404  # oturum, Access yerine geçmez


def test_student_session_with_token_of_admin_only_counts_token(
        access_client: TestClient, mailer: ConsoleMailer) -> None:
    login(access_client, mailer)  # listede olmayan öğrenci oturumu
    assert page(access_client, mint()).status_code == 200  # kimlik yalnızca JWT'den gelir
    assert page(access_client, None).status_code == 404


# --- Anahtar önbelleği --------------------------------------------------------------------------


def test_keys_are_cached_and_forged_kids_cannot_flood(jwks_calls: list[str]) -> None:
    now = [1000.0]
    v = AccessVerifier(TEAM, AUD, clock=lambda: now[0])
    assert v.email(mint()) == ADMIN
    assert v.email(mint()) == ADMIN
    assert len(jwks_calls) == 1
    for i in range(20):  # sahte kid art arda: en çok bir yenileme denemesi
        assert v.email(mint(kid=f"sahte{i}")) is None
    assert len(jwks_calls) == 1
    now[0] += access_module.KEYS_RETRY_SECONDS + 1
    assert v.email(mint(kid="sahte")) is None
    assert len(jwks_calls) == 2


def test_rotated_key_is_picked_up(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = [jwk()]
    monkeypatch.setattr(access_module, "fetch_jwks", lambda team: {"keys": list(keys)})
    now = [1000.0]
    v = AccessVerifier(TEAM, AUD, clock=lambda: now[0])
    assert v.email(mint()) == ADMIN
    keys.append(jwk(OTHER_PRIVATE, "k2"))
    now[0] += access_module.KEYS_RETRY_SECONDS + 1
    assert v.email(mint(OTHER_PRIVATE, "k2")) == ADMIN


def test_failed_refresh_keeps_keys_only_until_max_age(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"up": True}

    def fetch(team: str) -> dict[str, Any]:
        if not state["up"]:
            raise OSError("ulasilamadi")
        return {"keys": [jwk()]}

    monkeypatch.setattr(access_module, "fetch_jwks", fetch)
    now = [1000.0]
    v = AccessVerifier(TEAM, AUD, clock=lambda: now[0])
    assert v.email(mint()) == ADMIN
    state["up"] = False
    now[0] += access_module.KEYS_REFRESH_SECONDS + 1
    assert v.email(mint()) == ADMIN  # kısa kesinti paneli kilitlemez
    now[0] += access_module.KEYS_MAX_AGE_SECONDS
    assert v.email(mint()) is None  # ama süresiz eski anahtarla çalışılmaz


@pytest.mark.parametrize("payload", [{}, {"keys": "x"}, {"keys": [{"kty": "EC", "kid": "k1"}]},
                                     {"keys": [{"kty": "RSA", "kid": "k1", "n": "!", "e": "!"}]}])
def test_malformed_key_set_is_rejected(monkeypatch: pytest.MonkeyPatch,
                                       payload: dict[str, Any]) -> None:
    monkeypatch.setattr(access_module, "fetch_jwks", lambda team: payload)
    assert AccessVerifier(TEAM, AUD).email(mint()) is None


# --- Ayarlar ------------------------------------------------------------------------------------


def _prod(settings: Settings, **kw: Any) -> Settings:
    return replace(settings, dev=False, base_url="https://sontez.example", **kw)


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNORA_ADMIN_EMAILS", ADMIN)
    monkeypatch.setenv("SYNORA_ACCESS_TEAM_DOMAIN", f" {TEAM.upper()} ")
    monkeypatch.setenv("SYNORA_ACCESS_AUD", AUD.upper())
    s = Settings.from_env()
    assert s.access_team_domain == TEAM and s.access_aud == AUD
    assert s.access_enabled and s.admin_enabled  # anahtar özeti olmadan da panel açık


@pytest.mark.parametrize("kw", [{"access_team_domain": TEAM}, {"access_aud": AUD}])
def test_half_configuration_stops_production(settings: Settings, kw: dict[str, str]) -> None:
    problems = _prod(settings, **kw).problems()
    assert any("SYNORA_ACCESS" in p for p in problems)


@pytest.mark.parametrize("domain", [
    "kotu.example.com",
    "cloudflareaccess.com",
    "a.b.cloudflareaccess.com",
    "sontez.cloudflareaccess.com.kotu.example",
    "sontez.cloudflareaccess.com/yol",
    "https://sontez.cloudflareaccess.com",
])
def test_foreign_team_domain_stops_production(settings: Settings, domain: str) -> None:
    prod = _prod(settings, access_team_domain=domain, access_aud=AUD)
    assert not prod.access_enabled
    assert any("SYNORA_ACCESS_TEAM_DOMAIN" in p for p in prod.problems())


def test_malformed_aud_stops_production(settings: Settings) -> None:
    prod = _prod(settings, access_team_domain=TEAM, access_aud="kisa")
    assert not prod.access_enabled
    assert any("SYNORA_ACCESS_AUD" in p for p in prod.problems())
