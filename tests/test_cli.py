import asyncio
import inspect
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.main import get_command
from typer.testing import CliRunner

from sonosify.cli import app, settings
from sonosify.cli.commands import playback
from sonosify.cli.runtime import async_command


def test_command_topology() -> None:
    root = get_command(app)

    assert set(root.commands) == {
        "config",
        "discover",
        "enqueue",
        "favorites",
        "mute",
        "next",
        "now-playing",
        "open",
        "pause",
        "play",
        "previous",
        "queue",
        "stop",
        "track",
        "volume",
        "volume-down",
        "volume-up",
        "watch",
    }
    assert set(root.commands["favorites"].commands) == {"list", "play"}
    assert set(root.commands["config"].commands) == {"clear", "set", "show"}


def test_async_command_awaits_handler_and_preserves_signature() -> None:
    @async_command
    async def handler(value: str, repeat: int = 1) -> str:
        await asyncio.sleep(0)
        return value * repeat

    assert inspect.signature(handler) == inspect.signature(handler.__wrapped__)
    assert handler("ok", repeat=2) == "okok"


def test_typer_invocation_awaits_async_command(monkeypatch: pytest.MonkeyPatch) -> None:
    paused = False

    class Client:
        async def pause(self) -> None:
            nonlocal paused
            paused = True

    @asynccontextmanager
    async def fake_client_for(room: str | None, ip: str | None):
        assert (room, ip) == ("Kitchen", None)
        yield Client()

    monkeypatch.setattr(playback, "client_for", fake_client_for)

    result = CliRunner().invoke(app, ["--format", "plain", "pause", "Kitchen"])

    assert result.exit_code == 0
    assert paused


def test_settings_round_trip_and_default_target(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_PATH", config_path)

    settings.save_config({"default_room": "Kitchen", "default_timeout": "3.0"})

    assert settings.load_config() == {
        "default_room": "Kitchen",
        "default_timeout": "3.0",
    }
    assert settings.resolve_target(None, None) == ("Kitchen", None)
    assert settings.resolve_target("Office", None) == ("Office", None)
