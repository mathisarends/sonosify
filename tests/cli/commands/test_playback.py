"""playback.py's five commands are identical one-line delegations to a
SonosClient method (no branching). Rather than repeat the same wiring
assertion five times, this confirms the Typer/async_command/client_for stack
works end-to-end for one representative command.
"""

from contextlib import asynccontextmanager

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner

from sonosify.cli.app import app
from sonosify.cli.commands import playback


def test_pause_command_resolves_target_and_awaits_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paused = False

    class _Client:
        async def pause(self) -> None:
            nonlocal paused
            paused = True

    @asynccontextmanager
    async def fake_client_for(room, ip, *, coordinator=True):
        assert (room, ip) == ("Kitchen", None)
        yield _Client()

    monkeypatch.setattr(playback, "client_for", fake_client_for)

    result = CliRunner().invoke(app, ["--format", "plain", "pause", "Kitchen"])

    assert result.exit_code == 0
    assert paused
