import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner

import sonosify.cli.commands.cloud as cloud_command
from sonosify.cli.app import app
from sonosify.cli.commands.cloud import _extract_code
from sonosify.cloud.models import OAuthToken

CLIENT_ID_ENV = "SONOSIFY_CLOUD_CLIENT_ID"
CLIENT_SECRET_ENV = "SONOSIFY_CLOUD_CLIENT_SECRET"
REDIRECT_URI_ENV = "SONOSIFY_CLOUD_REDIRECT_URI"


@pytest.fixture(autouse=True)
def _clear_cloud_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (CLIENT_ID_ENV, CLIENT_SECRET_ENV, REDIRECT_URI_ENV):
        monkeypatch.delenv(name, raising=False)


def test_auth_url_reports_missing_environment_as_structured_error() -> None:
    result = CliRunner().invoke(app, ["cloud", "auth-url", "--format", "json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["code"] == "cloud_configuration_error"
    assert error["missing"] == [CLIENT_ID_ENV, REDIRECT_URI_ENV]


def test_auth_url_uses_environment_and_never_needs_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CLIENT_ID_ENV, "client")
    monkeypatch.setenv(REDIRECT_URI_ENV, "https://example.test/callback")

    result = CliRunner().invoke(
        app,
        ["cloud", "auth-url", "--state", "known-state", "--format", "json"],
    )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    query = parse_qs(urlparse(output["authorization_url"]).query)
    assert output["state"] == "known-state"
    assert query["client_id"] == ["client"]
    assert query["state"] == ["known-state"]


def test_extract_code_passes_through_a_bare_code() -> None:
    assert _extract_code("AUTHORIZATION_CODE") == "AUTHORIZATION_CODE"


def test_extract_code_pulls_code_out_of_a_redirect_url() -> None:
    url = "http://localhost:8000/callback?state=xyz&code=AUTHORIZATION_CODE"
    assert _extract_code(url) == "AUTHORIZATION_CODE"


def test_login_rejects_a_redirect_url_without_a_code() -> None:
    result = CliRunner().invoke(
        app, ["cloud", "login", "http://localhost:8000/callback?state=xyz"]
    )

    assert result.exit_code == 2
    assert "code" in result.output


class _FakeAuth:
    """Stand-in for SonosCloudAuth that skips real OAuth/network calls."""

    cached_token: OAuthToken | None = None

    def __init__(self) -> None:
        self.token_cache_path = Path("/fake/cloud-token.json")
        self._token = type(self).cached_token
        self.exchanged_with: str | None = None
        self.refreshed_with: str | None = None
        self.cleared = False

    @classmethod
    def from_environment(cls) -> "_FakeAuth":
        return cls()

    def get_authorization_url(self, state: str | None = None) -> str:
        return "https://api.sonos.com/login/v3/oauth?client_id=fake"

    def load_token(self) -> OAuthToken | None:
        return self._token

    async def async_exchange_code(self, code: str) -> OAuthToken:
        self.exchanged_with = code
        self._token = OAuthToken(access_token="new-access", expires_in=3600)
        return self._token

    async def async_refresh_token(self, refresh_token: str | None = None) -> OAuthToken:
        self.refreshed_with = refresh_token
        self._token = OAuthToken(access_token="refreshed-access", expires_in=3600)
        return self._token

    def clear_token(self) -> None:
        self.cleared = True
        self._token = None


@pytest.fixture(autouse=True)
def _reset_fake_auth() -> None:
    _FakeAuth.cached_token = None


def test_login_wizard_onboards_when_no_token_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cloud_command, "SonosCloudAuth", _FakeAuth)

    result = CliRunner().invoke(
        app,
        ["cloud", "login"],
        input="http://localhost:8000/callback?code=abc123\n",
    )

    assert result.exit_code == 0, result.output
    assert "authorized" in result.output
    assert "Open this URL in your browser" in result.output


def test_login_offers_refresh_for_an_existing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAuth.cached_token = OAuthToken(
        access_token="old-access",
        refresh_token="old-refresh",
        expires_in=3600,
        obtained_at=time.time(),
    )
    monkeypatch.setattr(cloud_command, "SonosCloudAuth", _FakeAuth)

    result = CliRunner().invoke(app, ["cloud", "login"], input="refresh\n")

    assert result.exit_code == 0, result.output
    assert "Already authorized" in result.output
    assert "refreshed" in result.output


def test_login_offers_removal_for_an_existing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeAuth.cached_token = OAuthToken(access_token="old-access", expires_in=3600)
    monkeypatch.setattr(cloud_command, "SonosCloudAuth", _FakeAuth)

    result = CliRunner().invoke(app, ["cloud", "login"], input="remove\n")

    assert result.exit_code == 0, result.output
    assert "removed" in result.output


def test_login_wizard_requires_plain_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cloud_command, "SonosCloudAuth", _FakeAuth)

    result = CliRunner().invoke(app, ["--format", "json", "cloud", "login"])

    assert result.exit_code == 2
    assert "plain" in result.output


def test_login_wizard_reports_missing_environment_as_structured_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "SONOSIFY_CLOUD_TOKEN_CACHE", str(tmp_path / "no-such-cache.json")
    )

    result = CliRunner().invoke(app, ["cloud", "login"])
    output = " ".join(result.output.split())

    assert result.exit_code == 1
    assert output == (
        f"error: missing Sonos cloud configuration: {CLIENT_ID_ENV}, {REDIRECT_URI_ENV}"
    )
