from contextlib import asynccontextmanager

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner

from sonosify.cli.app import app
from sonosify.cli.commands import queue as queue_module


class _Client:
    async def enqueue_uri(self, uri, *, next_, play):  # type: ignore[no-untyped-def]
        return 4


def _with_client(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def fake_client_for(room, ip, *, coordinator=True):
        yield _Client()

    monkeypatch.setattr(queue_module, "client_for", fake_client_for)


def test_enqueue_reports_enqueued_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_client(monkeypatch)

    result = CliRunner().invoke(app, ["enqueue", "x-sonos:1"])

    assert result.exit_code == 0
    assert "enqueued" in result.output


def test_enqueue_reports_playing_with_play_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_client(monkeypatch)

    result = CliRunner().invoke(app, ["enqueue", "x-sonos:1", "--play"])

    assert result.exit_code == 0
    assert "playing" in result.output


def test_queue_management_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int | None]] = []

    class _ManagementClient:
        async def clear_queue(self) -> None:
            calls.append(("clear", None))

        async def remove_queue_item(self, position: int) -> None:
            calls.append(("remove", position))

        async def seek_queue(self, position: int) -> None:
            calls.append(("jump", position))

        async def play(self) -> None:
            calls.append(("play", None))

    @asynccontextmanager
    async def fake_client_for(room, ip, *, coordinator=True):
        yield _ManagementClient()

    monkeypatch.setattr(queue_module, "client_for", fake_client_for)

    assert CliRunner().invoke(app, ["queue", "clear"]).exit_code == 0
    assert CliRunner().invoke(app, ["queue", "remove", "4"]).exit_code == 0
    assert CliRunner().invoke(app, ["queue", "jump", "7"]).exit_code == 0
    assert calls == [
        ("clear", None),
        ("remove", 4),
        ("jump", 7),
        ("play", None),
    ]
