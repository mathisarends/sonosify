from pathlib import Path

import pytest

from sonosify.cli import settings


def test_load_config_missing_file_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "missing.json")

    assert settings.load_config() == {}


def test_load_config_malformed_file_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(settings, "CONFIG_PATH", config_path)

    assert settings.load_config() == {}


def test_load_config_non_dict_json_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(settings, "CONFIG_PATH", config_path)

    assert settings.load_config() == {}


def test_save_config_round_trips_and_creates_parent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "nested" / "config.json"
    monkeypatch.setattr(settings, "CONFIG_PATH", config_path)

    settings.save_config({"default_room": "Kitchen", "default_timeout": "3.0"})

    assert settings.load_config() == {
        "default_room": "Kitchen",
        "default_timeout": "3.0",
    }


def test_resolve_target_prefers_explicit_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_PATH", config_path)
    settings.save_config({"default_room": "Kitchen"})

    assert settings.resolve_target("Office", None) == ("Office", None)
    assert settings.resolve_target(None, "10.0.0.1") == (None, "10.0.0.1")


def test_resolve_target_falls_back_to_configured_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_PATH", config_path)
    settings.save_config({"default_ip": "10.0.0.1"})

    assert settings.resolve_target(None, None) == (None, "10.0.0.1")


def test_resolve_target_ignores_non_string_config_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_PATH", config_path)
    settings.save_config({"default_room": 123})

    assert settings.resolve_target(None, None) == (None, None)
