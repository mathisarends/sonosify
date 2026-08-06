import asyncio
import os
import secrets
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlencode

import httpx
from pydantic import ValidationError

from sonosify.cloud.cache_handler import CacheFileHandler, CacheHandler
from sonosify.cloud.errors import (
    CloudAuthenticationError,
    CloudConfigurationError,
)
from sonosify.cloud.models import OAuthToken
from sonosify.cloud.settings import _CloudSettings

_AUTHORIZATION_URL = "https://api.sonos.com/login/v3/oauth"
_TOKEN_URL = "https://api.sonos.com/login/v3/oauth/access"
_DEFAULT_SCOPE = "playback-control-all"

_CLIENT_ID_ENV = "SONOSIFY_CLOUD_CLIENT_ID"
_CLIENT_SECRET_ENV = "SONOSIFY_CLOUD_CLIENT_SECRET"
_REDIRECT_URI_ENV = "SONOSIFY_CLOUD_REDIRECT_URI"
_ACCESS_TOKEN_ENV = "SONOSIFY_CLOUD_ACCESS_TOKEN"
_TOKEN_CACHE_ENV = "SONOSIFY_CLOUD_TOKEN_CACHE"


def _default_token_cache_path(override: Path | None = None) -> Path:
    if override:
        return override.expanduser()
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
        cache_handler: CacheHandler | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if token_cache_path is not None and cache_handler is not None:
            raise ValueError(
                "token_cache_path and cache_handler are mutually exclusive"
            )
        settings = _CloudSettings()
        settings_secret = (
            settings.client_secret.get_secret_value()
            if settings.client_secret is not None
            else None
        )
        settings_token = (
            settings.access_token.get_secret_value()
            if settings.access_token is not None
            else None
        )
        self._client_id = client_id or settings.client_id
        self._client_secret = client_secret or settings_secret
        self._redirect_uri = redirect_uri or settings.redirect_uri
        self._environment_token = access_token or settings_token
        self.cache_handler = cache_handler or CacheFileHandler(
            token_cache_path or _default_token_cache_path(settings.token_cache)
        )
        self._http = http_client
        self._refresh_lock = asyncio.Lock()

    @property
    def token_cache_path(self) -> Path | None:
        if isinstance(self.cache_handler, CacheFileHandler):
            return self.cache_handler.cache_path
        return None

    @classmethod
    def from_environment(cls) -> Self:
        return cls()

    def get_authorization_url(self, state: str | None = None) -> str:
        """Build the Sonos login URL and generate a state value when omitted."""
        self._require(_CLIENT_ID_ENV, _REDIRECT_URI_ENV)
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "state": state or secrets.token_urlsafe(32),
                "scope": _DEFAULT_SCOPE,
                "redirect_uri": self._redirect_uri,
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
                "redirect_uri": self._redirect_uri,
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
                f"{_TOKEN_CACHE_ENV} (cache populated via async_exchange_code)",
            )

    def load_token(self) -> OAuthToken | None:
        try:
            payload = self.cache_handler.get_cached_token()
            if payload is None:
                return None
            return OAuthToken.model_validate(payload)
        except ValidationError:
            return None

    def save_token(self, token: OAuthToken) -> None:
        self.cache_handler.save_token_to_cache(
            token.model_dump(mode="json", by_alias=True)
        )

    def clear_token(self) -> None:
        self.cache_handler.clear_cached_token()

    def _require(self, *names: str) -> None:
        values = {
            _CLIENT_ID_ENV: self._client_id,
            _CLIENT_SECRET_ENV: self._client_secret,
            _REDIRECT_URI_ENV: self._redirect_uri,
        }
        missing = [name for name in names if not values.get(name)]
        if missing:
            raise CloudConfigurationError(*missing)

    async def _request_token(self, data: dict[str, Any]) -> OAuthToken:
        assert self._client_id is not None
        assert self._client_secret is not None
        try:
            if self._http is not None:
                response = await self._http.post(
                    _TOKEN_URL,
                    data=data,
                    auth=(self._client_id, self._client_secret),
                )
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        _TOKEN_URL,
                        data=data,
                        auth=(self._client_id, self._client_secret),
                    )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("token response is not an object")
            return OAuthToken.model_validate(payload)
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise CloudAuthenticationError("Sonos OAuth token request failed") from exc
