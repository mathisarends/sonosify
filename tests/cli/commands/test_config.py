import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner

from sonosify.cli import settings
from sonosify.cli.app import app


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config.json")


def test_set_without_any_option_is_rejected() -> None:
    result = CliRunner().invoke(app, ["config", "set"])

    assert result.exit_code != 0
    assert settings.load_config() == {}


def test_setting_room_clears_a_previously_set_ip() -> None:
    runner = CliRunner()
    runner.invoke(app, ["config", "set", "--ip", "10.0.0.1"])

    result = runner.invoke(app, ["config", "set", "--room", "Kitchen"])

    assert result.exit_code == 0
    config = settings.load_config()
    assert config["default_room"] == "Kitchen"
    assert "default_ip" not in config


def test_setting_ip_clears_a_previously_set_room() -> None:
    runner = CliRunner()
    runner.invoke(app, ["config", "set", "--room", "Kitchen"])

    result = runner.invoke(app, ["config", "set", "--ip", "10.0.0.1"])

    assert result.exit_code == 0
    config = settings.load_config()
    assert config["default_ip"] == "10.0.0.1"
    assert "default_room" not in config
