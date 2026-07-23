from typing import Annotated

from sonosify.cli._dependencies import typer
from sonosify.cli.console import console
from sonosify.cli.output import print_action, print_object
from sonosify.cli.settings import CONFIG_PATH, load_config, save_config
from sonosify.cli.state import OutputFormat

app = typer.Typer(help="Manage local CLI defaults (e.g. the default speaker).")


@app.command("show")
def show() -> None:
    """Show the current local CLI defaults."""
    config = load_config()

    def plain() -> None:
        if not config:
            console.print(f"[dim]no config set[/] ({CONFIG_PATH})")
            return
        for key, value in config.items():
            if isinstance(value, dict):
                entries = "entry" if len(value) == 1 else "entries"
                console.print(f"{key}: [dim]<{len(value)} {entries}>[/]")
            else:
                console.print(f"{key}: [cyan]{value}[/]")

    print_object(dict(config), plain)


@app.command("set")
def set_defaults(
    room: Annotated[
        str | None, typer.Option("--room", "-r", help="Set the default room name.")
    ] = None,
    ip: Annotated[
        str | None, typer.Option("--ip", help="Set the default speaker IP.")
    ] = None,
    output_format: Annotated[
        OutputFormat | None,
        typer.Option("--format", help="Set the default output format."),
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option(
            "--timeout", help="Set the default SOAP/discovery timeout (seconds)."
        ),
    ] = None,
) -> None:
    """Set persistent CLI defaults so you don't have to pass them every time."""
    if room is None and ip is None and output_format is None and timeout is None:
        raise typer.BadParameter(
            "provide at least one of --room, --ip, --format, --timeout"
        )

    config = load_config()
    if room is not None:
        config["default_room"] = room
        config.pop("default_ip", None)
    if ip is not None:
        config["default_ip"] = ip
        config.pop("default_room", None)
    if output_format is not None:
        config["default_format"] = output_format.value
    if timeout is not None:
        config["default_timeout"] = str(timeout)
    save_config(config)
    print_action(f"[green]saved[/] config → {config}", {"status": "saved", **config})


@app.command("clear")
def clear() -> None:
    """Remove all local CLI defaults."""
    CONFIG_PATH.unlink(missing_ok=True)
    print_action("[green]config cleared[/]", {"status": "cleared"})
