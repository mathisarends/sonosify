import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from sonosify.cloud import (
    CloudConfigurationError,
    OAuthToken,
    SonosCloudAuth,
)

ACCESS_TOKEN_ENV = "SONOSIFY_CLOUD_ACCESS_TOKEN"
CLIENT_ID_ENV = "SONOSIFY_CLOUD_CLIENT_ID"
CLIENT_SECRET_ENV = "SONOSIFY_CLOUD_CLIENT_SECRET"
REDIRECT_URI_ENV = "SONOSIFY_CLOUD_REDIRECT_URI"
TOKEN_URL = "https://api.sonos.com/login/v3/oauth/access"


@pytest.fixture(autouse=True)
def _clear_cloud_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        ACCESS_TOKEN_ENV,
        CLIENT_ID_ENV,
        CLIENT_SECRET_ENV,
        REDIRECT_URI_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def test_authorization_url_is_encoded_and_requires_configuration() -> None:
    auth = SonosCloudAuth(
        client_id="client id",
        redirect_uri="https://example.test/oauth/callback?source=sonosify",
    )

    url = auth.get_authorization_url("csrf-state")
    query = parse_qs(urlparse(url).query)

    assert query == {
        "client_id": ["client id"],
        "redirect_uri": ["https://example.test/oauth/callback?source=sonosify"],
        "response_type": ["code"],
        "scope": ["playback-control-all"],
        "state": ["csrf-state"],
    }

    with pytest.raises(CloudConfigurationError) as excinfo:
        SonosCloudAuth().get_authorization_url("state")

    assert excinfo.value.missing == (CLIENT_ID_ENV, REDIRECT_URI_ENV)


def test_exchange_code_uses_basic_auth_and_persists_token(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["Authorization"]
        seen["body"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    cache = tmp_path / "cloud-token.json"

    async def run() -> OAuthToken:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            auth = SonosCloudAuth(
                "client",
                "secret",
                "https://example.test/callback",
                token_cache_path=cache,
                http_client=client,
            )
            return await auth.async_exchange_code("authorization-code")

    token = asyncio.run(run())

    assert seen["url"] == TOKEN_URL
    assert str(seen["authorization"]).startswith("Basic ")
    assert seen["body"] == {
        "grant_type": ["authorization_code"],
        "code": ["authorization-code"],
        "redirect_uri": ["https://example.test/callback"],
    }
    assert token.access_token == "access"
    cached = json.loads(cache.read_text(encoding="utf-8"))
    assert cached["accessToken"] == "access"
    assert cached["refreshToken"] == "refresh"
    assert "secret" not in cache.read_text(encoding="utf-8")


def test_get_valid_token_uses_environment_without_client_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ACCESS_TOKEN_ENV, "temporary-token")

    token = asyncio.run(SonosCloudAuth.from_environment().async_get_valid_token())

    assert token == "temporary-token"


def test_from_environment_loads_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "SONOSIFY_CLOUD_CLIENT_ID=dotenv-client",
                "SONOSIFY_CLOUD_CLIENT_SECRET=dotenv-secret",
                "SONOSIFY_CLOUD_REDIRECT_URI=https://example.test/callback",
                "SONOSIFY_CLOUD_ACCESS_TOKEN=dotenv-token",
                "SONOSIFY_CLOUD_TOKEN_CACHE=./tokens/cloud.json",
            )
        ),
        encoding="utf-8",
    )

    auth = SonosCloudAuth.from_environment()

    query = parse_qs(urlparse(auth.get_authorization_url("state")).query)
    assert query["client_id"] == ["dotenv-client"]
    assert query["redirect_uri"] == ["https://example.test/callback"]
    assert auth.token_cache_path == Path("tokens/cloud.json")
    assert asyncio.run(auth.async_get_valid_token()) == "dotenv-token"


def test_expired_cached_token_is_refreshed_and_rotation_is_optional(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cloud-token.json"
    cache.write_text(
        OAuthToken(
            access_token="expired",
            refresh_token="keep-me",
            expires_in=1,
            obtained_at=0,
        ).model_dump_json(by_alias=True),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert parse_qs(request.content.decode()) == {
            "grant_type": ["refresh_token"],
            "refresh_token": ["keep-me"],
        }
        return httpx.Response(
            200,
            json={"access_token": "fresh", "expires_in": 3600},
        )

    async def run() -> str:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            auth = SonosCloudAuth(
                "client",
                "secret",
                token_cache_path=cache,
                http_client=client,
            )
            return await auth.async_get_valid_token()

    assert asyncio.run(run()) == "fresh"
    assert (
        SonosCloudAuth(token_cache_path=cache).load_token().refresh_token == "keep-me"
    )  # type: ignore[union-attr]
