"""Cloudflare Access kimliğini uygulamada doğrular (yönetim paneli).

Access önde kimliği sorar ve isteğe imzalı bir JWT ekler (`Cf-Access-Jwt-Assertion`). Access yanlış
ayarlanır ya da yol kuralı atlatılırsa panel açılmasın diye jeton burada da denetlenir: yalnızca
RS256, ekibin açık anahtarları, `aud`, `iss`, `exp`, `nbf`. Şüphede yanıt her zaman "kimlik yok".
Jeton ve e-posta loglanmaz.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.request
from collections.abc import Callable
from typing import Any

import jwt

from synora.log import log_event

ALGORITHM = "RS256"
MAX_TOKEN_CHARS = 8192
MAX_JWKS_BYTES = 64 * 1024
FETCH_TIMEOUT_SECONDS = 5
LEEWAY_SECONDS = 30  # sunucu saati kayması
KEYS_REFRESH_SECONDS = 3600.0  # bu kadar eskiyen anahtarlar yenilenmeye çalışılır
KEYS_RETRY_SECONDS = 60.0  # iki deneme arası en az: sahte `kid` ile istek yağdırılamasın
KEYS_MAX_AGE_SECONDS = 24 * 3600.0  # yenilenemeyen anahtarla en çok bu kadar çalışılır


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # anahtarlar yalnızca ekibin kendi adresinden alınır


_OPENER = urllib.request.build_opener(_NoRedirect)


def fetch_jwks(team_domain: str) -> dict[str, Any]:
    """Ekibin açık anahtarları. Alan adı ayarda *.cloudflareaccess.com olarak doğrulanmıştır."""
    url = f"https://{team_domain}/cdn-cgi/access/certs"
    with _OPENER.open(url, timeout=FETCH_TIMEOUT_SECONDS) as response:
        body = response.read(MAX_JWKS_BYTES + 1)
    if len(body) > MAX_JWKS_BYTES:
        raise ValueError("anahtar yanıtı çok büyük")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("anahtar yanıtı beklenen biçimde değil")
    return parsed


def _parse_keys(payload: dict[str, Any]) -> dict[str, Any]:
    keys: dict[str, Any] = {}
    entries = payload.get("keys")
    for entry in entries if isinstance(entries, list) else []:
        if not (isinstance(entry, dict) and entry.get("kty") == "RSA"
                and isinstance(entry.get("kid"), str)):
            continue
        try:
            keys[entry["kid"]] = jwt.PyJWK.from_dict(entry, algorithm=ALGORITHM).key
        except (jwt.PyJWTError, ValueError, TypeError):
            continue
    return keys


class AccessVerifier:
    def __init__(self, team_domain: str, aud: str,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.team_domain = team_domain
        self.aud = aud
        self.issuer = f"https://{team_domain}"
        self._clock = clock
        self._lock = threading.Lock()
        self._keys: dict[str, Any] = {}
        self._fetched_at = float("-inf")
        self._attempted_at = float("-inf")

    def _refresh(self, now: float) -> None:
        self._attempted_at = now
        try:
            keys = _parse_keys(fetch_jwks(self.team_domain))
        except (OSError, ValueError, http.client.HTTPException):
            keys = {}
        if keys:
            self._keys, self._fetched_at = keys, now
        else:
            log_event("admin.access_keys_unavailable")

    def _key_for(self, kid: str) -> Any:
        now = self._clock()
        with self._lock:
            due = kid not in self._keys or now - self._fetched_at >= KEYS_REFRESH_SECONDS
            if due and now - self._attempted_at >= KEYS_RETRY_SECONDS:
                self._refresh(now)
            if now - self._fetched_at >= KEYS_MAX_AGE_SECONDS:
                self._keys = {}
            return self._keys.get(kid)

    def email(self, token: str | None) -> str | None:
        """Jeton her yönden geçerliyse küçük harfli e-posta; değilse None."""
        if not token or len(token) > MAX_TOKEN_CHARS:
            return None
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != ALGORITHM or not isinstance(kid, str):
                return None
            key = self._key_for(kid)
            if key is None:
                return None
            claims = jwt.decode(token, key, algorithms=[ALGORITHM], audience=self.aud,
                                issuer=self.issuer, leeway=LEEWAY_SECONDS,
                                options={"require": ["exp", "aud", "iss"]})
        except jwt.PyJWTError:
            return None
        email = claims.get("email")  # servis jetonlarında e-posta yok: kişi sayılmaz
        return email.strip().lower() if isinstance(email, str) and email.strip() else None
