from contextlib import asynccontextmanager

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner

from sonosify.cli.app import app
from sonosify.cli.commands import media


class _Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def open_track(self, track_id, *, next_, play):  # type: ignore[no-untyped-def]
        self.calls.append({"track_id": track_id, "next_": next_, "play": play})
        return 3


def _with_client(monkeypatch: pytest.MonkeyPatch, client: _Client) -> None:
    @asynccontextmanager
    async def fake_client_for(room, ip, *, coordinator=True):
        yield client

    monkeypatch.setattr(media, "client_for", fake_client_for)


def test_track_enqueue_only_flag_disables_playback_and_reports_enqueued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    _with_client(monkeypatch, client)

    result = CliRunner().invoke(app, ["track", "abc123", "--enqueue"])

    assert result.exit_code == 0
    assert client.calls == [{"track_id": "abc123", "next_": False, "play": False}]
    assert "enqueued" in result.output


def test_track_without_enqueue_flag_plays_and_reports_playing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    _with_client(monkeypatch, client)

    result = CliRunner().invoke(app, ["track", "abc123"])

    assert result.exit_code == 0
    assert client.calls == [{"track_id": "abc123", "next_": False, "play": True}]
    assert "playing" in result.output
