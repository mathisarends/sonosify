import json
import os
from pathlib import Path

from sonosify.cli._dependencies import typer

CONFIG_PATH = Path(typer.get_app_dir("sonosify")) / "config.json"


def load_config() -> dict[str, object]:
    """Load CLI defaults, treating a missing or malformed file as empty."""
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return config if isinstance(config, dict) else {}


def save_config(config: dict[str, object]) -> None:
    """Persist CLI defaults in the platform-specific application directory."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def env_value(name: str) -> str | None:
    value = os.environ.get(f"SONOSIFY_{name}")
    return value if value else None


def resolve_target(room: str | None, ip: str | None) -> tuple[str | None, str | None]:
    """Apply environment and configured defaults to a target."""
    if room or ip:
        return room, ip

    config = load_config()
    default_room = env_value("ROOM") or config.get("default_room")
    default_ip = env_value("IP") or config.get("default_ip")
    return (
        default_room if isinstance(default_room, str) else None,
        default_ip if isinstance(default_ip, str) else None,
    )


def cached_ip(room: str) -> str | None:
    """Return a cached IP for an exact room name."""
    speakers = load_config().get("speakers")
    if not isinstance(speakers, dict):
        return None
    normalized = room.casefold()
    matches = [
        value.get("ip")
        for key, value in speakers.items()
        if isinstance(key, str)
        and key.casefold() == normalized
        and isinstance(value, dict)
    ]
    return matches[0] if matches and isinstance(matches[0], str) else None


def save_speaker_cache(records: list[dict[str, object]]) -> None:
    """Persist discovered room, IP, and UID mappings."""
    config = load_config()
    config["speakers"] = {
        str(record["room"]): {
            "ip": record["ip"],
            "uid": record["uid"],
        }
        for record in records
        if record.get("room") and record.get("ip")
    }
    save_config(config)
