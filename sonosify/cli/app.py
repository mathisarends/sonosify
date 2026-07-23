import logging
from typing import Annotated

from sonosify.cli._dependencies import typer
from sonosify.cli.commands import (
    config,
    discovery,
    favorites,
    media,
    playback,
    queue,
    volume,
)
from sonosify.cli.settings import env_value, load_config
from sonosify.cli.state import OutputFormat, state
from sonosify.client import DEFAULT_TIMEOUT

app = typer.Typer(
    name="sonosify",
    help="Discover and control Sonos speakers from the command line.",
    no_args_is_help=True,
    add_completion=False,
)

discovery.register(app)
playback.register(app)
volume.register(app)
queue.register(app)
app.add_typer(favorites.app, name="favorites")
media.register(app)
app.add_typer(config.app, name="config")


@app.callback()
def main(
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
    if debug:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
        sonos_logger = logging.getLogger("sonosify")
        sonos_logger.setLevel(logging.DEBUG)
        sonos_logger.addHandler(handler)
