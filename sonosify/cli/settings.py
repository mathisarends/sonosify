import json
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


def resolve_target(room: str | None, ip: str | None) -> tuple[str | None, str | None]:
    """Apply the configured default speaker when no explicit target is given."""
    if room or ip:
        return room, ip

    config = load_config()
    default_room = config.get("default_room")
    default_ip = config.get("default_ip")
    return (
        default_room if isinstance(default_room, str) else None,
        default_ip if isinstance(default_ip, str) else None,
    )
