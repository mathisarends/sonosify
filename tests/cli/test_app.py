import importlib
import logging

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.main import get_command
from typer.testing import CliRunner

from sonosify.cli.app import app
from sonosify.cli.state import OutputFormat, state

# `sonosify.cli.__init__` re-exports `app` (the Typer instance) under the same
# name as the `sonosify.cli.app` submodule, which shadows the submodule on the
# `sonosify.cli` package object. Go through sys.modules via importlib to reach
# the actual module and monkeypatch its `load_config` reference.
app_module = importlib.import_module("sonosify.cli.app")


def test_command_topology() -> None:
    root = get_command(app)

    assert set(root.commands) == {
        "cloud",
        "commands",
        "config",
        "crossfade",
        "discover",
        "doctor",
        "enqueue",
        "favorites",
        "group",
        "groups",
        "get-volume",
        "mute",
        "next",
        "now-playing",
        "open",
        "pause",
        "ping",
        "play",
        "previous",
        "queue",
        "repeat",
        "seek",
        "set-volume",
        "shuffle",
        "sleep",
        "stop",
        "status",
        "track",
        "ungroup",
        "volume",
        "volume-down",
        "volume-up",
        "watch",
    }
    assert set(root.commands["favorites"].commands) == {"list", "play"}
    assert set(root.commands["config"].commands) == {"clear", "set", "show"}
    assert set(root.commands["queue"].commands) == {"clear", "jump", "remove"}
    assert set(root.commands["cloud"].commands) == {
        "auth-url",
        "clip",
        "groups",
        "households",
        "login",
        "logout",
        "next",
        "pause",
        "play",
        "players",
        "previous",
    }


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    state.configure(format=OutputFormat.PLAIN, debug=False, timeout=15.0)


def test_main_uses_explicit_flags_over_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        app_module,
        "load_config",
        lambda: {"default_format": "json", "default_timeout": "9.0"},
    )

    result = CliRunner().invoke(
        app, ["--format", "tsv", "--timeout", "3.0", "config", "show"]
    )

    assert result.exit_code == 0
    assert state.format == OutputFormat.TSV
    assert state.timeout == 3.0


def test_main_falls_back_to_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        app_module,
        "load_config",
        lambda: {"default_format": "json", "default_timeout": "9.0"},
    )

    result = CliRunner().invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert state.format == OutputFormat.JSON
    assert state.timeout == 9.0


def test_global_options_are_accepted_after_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "load_config", lambda: {})

    result = CliRunner().invoke(app, ["config", "show", "--format", "json"])

    assert result.exit_code == 0
    assert state.format is OutputFormat.JSON


def test_version_and_command_introspection_are_machine_readable() -> None:
    version_result = CliRunner().invoke(app, ["--format", "json", "--version"])
    commands_result = CliRunner().invoke(app, ["commands", "--format", "json"])

    assert version_result.exit_code == 0
    assert '"version"' in version_result.stdout
    assert commands_result.exit_code == 0
    assert '"parameters"' in commands_result.stdout


def test_main_debug_flag_attaches_debug_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "load_config", lambda: {})
    sonos_logger = logging.getLogger("sonosify")
    original_handlers = list(sonos_logger.handlers)
    original_level = sonos_logger.level

    try:
        result = CliRunner().invoke(app, ["--debug", "config", "show"])

        assert result.exit_code == 0
        assert state.debug is True
        assert sonos_logger.level == logging.DEBUG
        assert len(sonos_logger.handlers) > len(original_handlers)
    finally:
        sonos_logger.handlers = original_handlers
        sonos_logger.setLevel(original_level)
