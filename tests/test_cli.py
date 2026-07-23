import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.main import get_command

from sonosify.cli import app, settings


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
