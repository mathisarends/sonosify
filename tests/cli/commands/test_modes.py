from contextlib import asynccontextmanager

import pytest
from typer.testing import CliRunner

from sonosify.cli.app import app
from sonosify.cli.commands import modes


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def seek(self, value: str) -> None:
        self.calls.append(("seek", value))

    async def set_shuffle(self, enabled: bool) -> str:
        self.calls.append(("shuffle", enabled))
        return "SHUFFLE" if enabled else "NORMAL"

    async def set_repeat(self, mode: object) -> str:
        self.calls.append(("repeat", mode))
        return "REPEAT_ALL"

    async def set_crossfade(self, enabled: bool) -> None:
        self.calls.append(("crossfade", enabled))

    async def configure_sleep_timer(self, duration: str | None) -> None:
        self.calls.append(("sleep", duration))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> _Client:
    client = _Client()

    @asynccontextmanager
    async def fake_client_for(room, ip, *, coordinator=True):
        yield client

    monkeypatch.setattr(modes, "client_for", fake_client_for)
    return client


@pytest.mark.parametrize(
    ("args", "call"),
    [
        (["seek", "1:30"], ("seek", "0:01:30")),
        (["shuffle", "on"], ("shuffle", True)),
        (["repeat", "all"], ("repeat", "all")),
        (["crossfade", "off"], ("crossfade", False)),
        (["sleep", "30m"], ("sleep", "0:30:00")),
        (["sleep", "off"], ("sleep", None)),
    ],
)
def test_playback_mode_commands(
    client: _Client, args: list[str], call: tuple[str, object]
) -> None:
    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    actual = client.calls[-1]
    assert actual[0] == call[0]
    assert str(actual[1]) == str(call[1])
