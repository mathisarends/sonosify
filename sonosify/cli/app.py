import logging
from importlib.metadata import version
from typing import Annotated

from sonosify.cli._dependencies import typer
from sonosify.cli.commands import (
    agent,
    cloud,
    config,
    discovery,
    favorites,
    groups,
    media,
    modes,
    playback,
    queue,
    volume,
)
from sonosify.cli.settings import env_value, load_config
from sonosify.cli.state import OutputFormat, state
from sonosify.client import DEFAULT_TIMEOUT


class GlobalOptionsGroup(typer.core.TyperGroup):
    """Allow root options to appear before or after a subcommand."""

    def parse_args(self, ctx: typer.Context, args: list[str]) -> list[str]:
        config_set = args[:2] == ["config", "set"]
        root_options: list[str] = []
        remaining: list[str] = []
        index = 0
        while index < len(args):
            value = args[index]
            if (
                value in {"--format", "--timeout"}
                and index + 1 < len(args)
                and not config_set
            ):
                root_options.extend((value, args[index + 1]))
                index += 2
                continue
            if (
                value.startswith(("--format=", "--timeout=")) and not config_set
            ) or value == "--debug":
                root_options.append(value)
            else:
                remaining.append(value)
            index += 1
        return super().parse_args(ctx, [*root_options, *remaining])


app = typer.Typer(
    name="sonosify",
    help="Discover and control Sonos speakers from the command line.",
    no_args_is_help=True,
    invoke_without_command=True,
    add_completion=False,
    cls=GlobalOptionsGroup,
)

discovery.register(app)
playback.register(app)
volume.register(app)
queue.register(app)
groups.register(app)
modes.register(app)
agent.register(app)
app.add_typer(favorites.app, name="favorites")
media.register(app)
app.add_typer(config.app, name="config")
app.add_typer(cloud.app, name="cloud")


@app.callback()
def main(
    version_requested: Annotated[
        bool,
        typer.Option("--version", help="Print the installed version and exit."),
    ] = False,
    output_format: Annotated[
        OutputFormat | None,
        typer.Option("--format", help="Output format for machine-readable scripting."),
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="SOAP / discovery timeout in seconds."),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Print SOAP request/response traces to stderr."),
    ] = False,
) -> None:
    """Discover and control Sonos speakers from the command line."""
    config_values = load_config()
    state.configure(
        format=output_format
        or OutputFormat(
            env_value("FORMAT")
            or config_values.get("default_format", OutputFormat.PLAIN)
        ),
        timeout=timeout
        if timeout is not None
        else float(
            env_value("TIMEOUT")
            or config_values.get("default_timeout", DEFAULT_TIMEOUT)
        ),
        debug=debug or env_value("DEBUG") in {"1", "true", "yes"},
    )
    if version_requested:
        if state.format is OutputFormat.JSON:
            typer.echo(f'{{"schema_version": 1, "version": "{version("sonosify")}"}}')
        else:
            typer.echo(version("sonosify"))
        raise typer.Exit()
    if debug:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
        sonos_logger = logging.getLogger("sonosify")
        sonos_logger.setLevel(logging.DEBUG)
        sonos_logger.addHandler(handler)
