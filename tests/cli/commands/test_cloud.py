import json
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner

from sonosify.cli.app import app

CLIENT_ID_ENV = "SONOSIFY_CLOUD_CLIENT_ID"
CLIENT_SECRET_ENV = "SONOSIFY_CLOUD_CLIENT_SECRET"
REDIRECT_URI_ENV = "SONOSIFY_CLOUD_REDIRECT_URI"


@pytest.fixture(autouse=True)
def _clear_cloud_environment(monkeypatch: pytest.MonkeyPatch) -> None:
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
