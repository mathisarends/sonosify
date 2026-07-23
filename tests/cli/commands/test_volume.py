from contextlib import asynccontextmanager

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner

from sonosify.cli.app import app
from sonosify.cli.commands import volume as volume_module


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.current_volume = 40
        self.muted = False

    async def get_volume(self) -> int:
        self.calls.append(("get_volume", None))
        return self.current_volume

    async def set_volume(self, level: int) -> None:
        self.calls.append(("set_volume", level))

    async def toggle_mute(self) -> bool:
        self.muted = not self.muted
        self.calls.append(("toggle_mute", None))
        return self.muted

    async def set_mute(self, on: bool) -> None:
        self.muted = on
        self.calls.append(("set_mute", on))


def _with_client(monkeypatch: pytest.MonkeyPatch, client: _Client) -> list:
    seen_rooms: list[str | None] = []

    @asynccontextmanager
    async def fake_client_for(room, ip, *, coordinator=True):
        seen_rooms.append(room)
        yield client

    monkeypatch.setattr(volume_module, "client_for", fake_client_for)
    return seen_rooms


def test_single_numeric_argument_is_treated_as_target_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    seen_rooms = _with_client(monkeypatch, client)

    result = CliRunner().invoke(app, ["volume", "50"])

    assert result.exit_code == 0
    assert client.calls == [("set_volume", 50)]
    assert seen_rooms == [None]


def test_single_non_numeric_argument_is_treated_as_room_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    seen_rooms = _with_client(monkeypatch, client)

    result = CliRunner().invoke(app, ["volume", "Kitchen"])

    assert result.exit_code == 0
    assert client.calls == [("get_volume", None)]
    assert seen_rooms == ["Kitchen"]


def test_room_and_level_given_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()
    seen_rooms = _with_client(monkeypatch, client)

    result = CliRunner().invoke(app, ["volume", "Kitchen", "50"])

    assert result.exit_code == 0
    assert client.calls == [("set_volume", 50)]
    assert seen_rooms == ["Kitchen"]


def test_mute_without_flag_toggles(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()
    _with_client(monkeypatch, client)

    result = CliRunner().invoke(app, ["mute"])

    assert result.exit_code == 0
    assert client.calls == [("toggle_mute", None)]


def test_mute_with_explicit_flag_sets_state(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()
    _with_client(monkeypatch, client)

    result = CliRunner().invoke(app, ["mute", "--off"])

    assert result.exit_code == 0
    assert client.calls == [("set_mute", False)]


def test_explicit_volume_commands_support_room_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    seen_rooms = _with_client(monkeypatch, client)

    get_result = CliRunner().invoke(app, ["get-volume", "--room", "Kitchen"])
    set_result = CliRunner().invoke(app, ["set-volume", "30", "--room", "Kitchen"])

    assert get_result.exit_code == 0
    assert set_result.exit_code == 0
    assert client.calls == [("get_volume", None), ("set_volume", 30)]
    assert seen_rooms == ["Kitchen", "Kitchen"]
