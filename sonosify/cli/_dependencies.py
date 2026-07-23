try:
    import typer
    from rich.console import Console
    from rich.table import Table
except ModuleNotFoundError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "The sonosify CLI requires the optional 'cli' dependencies. "
        "Install them with: pip install 'sonosify[cli]'"
    ) from exc

__all__ = ["Console", "Table", "typer"]
