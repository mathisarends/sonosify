from __future__ import annotations

import asyncio
import json
import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import ValidationError

from sonosify.cloud.errors import (
    CloudAuthenticationError,
    CloudConfigurationError,
)
from sonosify.cloud.models import OAuthToken

_AUTHORIZATION_URL = "https://api.sonos.com/login/v3/oauth"
_TOKEN_URL = "https://api.sonos.com/login/v3/oauth/access"
_DEFAULT_SCOPE = "playback-control-all"

_CLIENT_ID_ENV = "SONOSIFY_CLOUD_CLIENT_ID"
_CLIENT_SECRET_ENV = "SONOSIFY_CLOUD_CLIENT_SECRET"
_REDIRECT_URI_ENV = "SONOSIFY_CLOUD_REDIRECT_URI"
_ACCESS_TOKEN_ENV = "SONOSIFY_CLOUD_ACCESS_TOKEN"
_TOKEN_CACHE_ENV = "SONOSIFY_CLOUD_TOKEN_CACHE"


def _default_token_cache_path() -> Path:
    override = os.environ.get(_TOKEN_CACHE_ENV)
    if override:
        return Path(override).expanduser()
    if os.name == "nt" and (appdata := os.environ.get("APPDATA")):
        return Path(appdata) / "sonosify" / "cloud-token.json"
    config_home = os.environ.get("XDG_CONFIG_HOME")
    root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return root / "sonosify" / "cloud-token.json"


class SonosCloudAuth:
    """Manage OAuth2 authorization, token refresh, and a local token cache."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        *,
        access_token: str | None = None,
        token_cache_path: Path | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client_id = client_id or os.environ.get(_CLIENT_ID_ENV)
        self.client_secret = client_secret or os.environ.get(_CLIENT_SECRET_ENV)
        self.redirect_uri = redirect_uri or os.environ.get(_REDIRECT_URI_ENV)
        self._environment_token = access_token or os.environ.get(_ACCESS_TOKEN_ENV)
        self.token_cache_path = token_cache_path or _default_token_cache_path()
        self._http = http_client
        self._refresh_lock = asyncio.Lock()

    @classmethod
    def from_environment(cls) -> SonosCloudAuth:
        """Create an auth manager using the documented SONOSIFY_CLOUD_* variables."""
        return cls()

    def get_authorization_url(self, state: str | None = None) -> str:
        """Build the Sonos login URL and generate a state value when omitted."""
        self._require(_CLIENT_ID_ENV, _REDIRECT_URI_ENV)
        query = urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "state": state or secrets.token_urlsafe(32),
                "scope": _DEFAULT_SCOPE,
                "redirect_uri": self.redirect_uri,
            }
        )
        return f"{_AUTHORIZATION_URL}?{query}"

    async def async_exchange_code(self, code: str) -> OAuthToken:
        """Exchange an authorization code and persist the returned token pair."""
        self._require(_CLIENT_ID_ENV, _CLIENT_SECRET_ENV, _REDIRECT_URI_ENV)
        token = await self._request_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            }
        )
        self.save_token(token)
        return token

    async def async_refresh_token(self, refresh_token: str | None = None) -> OAuthToken:
        """Refresh and persist an OAuth token."""
        self._require(_CLIENT_ID_ENV, _CLIENT_SECRET_ENV)
        previous = self.load_token()
        value = refresh_token or (previous.refresh_token if previous else "")
        if not value:
            raise CloudConfigurationError(
                f"{_TOKEN_CACHE_ENV} (cache containing a refresh token)"
            )
        token = await self._request_token(
            {"grant_type": "refresh_token", "refresh_token": value}
        )
        if not token.refresh_token:
            token = token.model_copy(update={"refresh_token": value})
        self.save_token(token)
        return token

    async def async_get_valid_token(self, *, force_refresh: bool = False) -> str:
        """Return a usable access token, refreshing the cached token if needed."""
        if self._environment_token and not force_refresh:
            return self._environment_token
        async with self._refresh_lock:
            token = self.load_token()
            if token and not force_refresh and not token.is_expired():
                return token.access_token
            if token and token.refresh_token:
                refreshed = await self.async_refresh_token(token.refresh_token)
                return refreshed.access_token
            if self._environment_token:
                return self._environment_token
            raise CloudConfigurationError(
                _ACCESS_TOKEN_ENV,
                f"{_TOKEN_CACHE_ENV} (cache created by `sonosify cloud login`)",
            )

    def load_token(self) -> OAuthToken | None:
        try:
            payload = json.loads(self.token_cache_path.read_text(encoding="utf-8"))
            return OAuthToken.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError):
            return None

    def save_token(self, token: OAuthToken) -> None:
        self.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_cache_path.write_text(
            token.model_dump_json(by_alias=True, indent=2),
            encoding="utf-8",
        )
        if os.name != "nt":
            self.token_cache_path.chmod(0o600)

    def clear_token(self) -> None:
        self.token_cache_path.unlink(missing_ok=True)

    def _require(self, *names: str) -> None:
        values = {
            _CLIENT_ID_ENV: self.client_id,
            _CLIENT_SECRET_ENV: self.client_secret,
            _REDIRECT_URI_ENV: self.redirect_uri,
        }
        missing = [name for name in names if not values.get(name)]
        if missing:
            raise CloudConfigurationError(*missing)

    async def _request_token(self, data: dict[str, Any]) -> OAuthToken:
        assert self.client_id is not None
        assert self.client_secret is not None
        try:
            if self._http is not None:
                response = await self._http.post(
                    _TOKEN_URL,
                    data=data,
                    auth=(self.client_id, self.client_secret),
                )
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        _TOKEN_URL,
                        data=data,
                        auth=(self.client_id, self.client_secret),
                    )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("token response is not an object")
            return OAuthToken.model_validate(payload)
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise CloudAuthenticationError("Sonos OAuth token request failed") from exc
