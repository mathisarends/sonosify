from contextlib import asynccontextmanager

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner

from sonosify import Favorite
from sonosify.cli.app import app
from sonosify.cli.commands import favorites


class _Client:
    def __init__(self, available: list[Favorite]) -> None:
        self._available = available
        self.opened: Favorite | None = None

    async def favorites(self) -> list[Favorite]:
        return self._available

    async def open_favorite(self, favorite: Favorite) -> None:
        self.opened = favorite


def _with_client(monkeypatch: pytest.MonkeyPatch, client: _Client) -> None:
    @asynccontextmanager
    async def fake_client_for(room, ip, *, coordinator=True):
        yield client

    monkeypatch.setattr(favorites, "client_for", fake_client_for)


def test_play_favorite_matches_by_case_insensitive_substring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client([Favorite(title="Jazz FM", uri="x-1")])
    _with_client(monkeypatch, client)

    result = CliRunner().invoke(app, ["favorites", "play", "jazz"])

    assert result.exit_code == 0
    assert client.opened == Favorite(title="Jazz FM", uri="x-1")


def test_play_favorite_reports_error_when_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client([Favorite(title="Jazz FM", uri="x-1")])
    _with_client(monkeypatch, client)

    result = CliRunner().invoke(app, ["favorites", "play", "rock"])

    assert result.exit_code == 1
    assert client.opened is None
    assert "no favorite matching" in result.output


def test_play_favorite_reports_error_when_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(
        [
            Favorite(title="Jazz FM", uri="x-1"),
            Favorite(title="Jazz Classics", uri="x-2"),
        ]
    )
    _with_client(monkeypatch, client)

    result = CliRunner().invoke(app, ["favorites", "play", "jazz"])

    assert result.exit_code == 1
    assert client.opened is None
    assert "ambiguous favorite" in result.output
