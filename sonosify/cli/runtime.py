import asyncio
import json
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any

from sonosify import SonosClient, SonosController
from sonosify.cli._dependencies import typer
from sonosify.cli.console import error_console
from sonosify.cli.settings import cached_ip, resolve_target
from sonosify.cli.state import OutputFormat, state
from sonosify.errors import (
    AmbiguousSpeakerError,
    DiscoveryError,
    NetworkError,
    SonosifyError,
    SpeakerNotFoundError,
    UPnPError,
)

EXIT_CODES = {
    SpeakerNotFoundError: 2,
    AmbiguousSpeakerError: 3,
    DiscoveryError: 4,
    NetworkError: 4,
    UPnPError: 5,
}


def error_details(exc: SonosifyError) -> dict[str, object]:
    data: dict[str, object] = {"schema_version": 1, "error": str(exc)}
    custom_details = getattr(exc, "error_details", None)
    if callable(custom_details):
        details = custom_details()
        if isinstance(details, dict):
            data.update(details)
            return data
    match exc:
        case AmbiguousSpeakerError():
            data.update(
                code="ambiguous_speaker", query=exc.query, matches=list(exc.matches)
            )
        case SpeakerNotFoundError():
            data.update(code="speaker_not_found")
            if exc.query is not None:
                data["query"] = exc.query
        case DiscoveryError():
            data.update(code="discovery_error")
        case NetworkError():
            data.update(code="network_error")
        case UPnPError():
            data.update(
                code="upnp_error",
                upnp_code=exc.code,
                description=exc.description,
            )
        case _:
            data.update(code="sonosify_error")
    return data


def async_command[**P, T](
    function: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, T]:
    """Adapt an async command handler to Typer's synchronous callback API."""

    @wraps(function)
    def invoke(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return asyncio.run(function(*args, **kwargs))
        except SonosifyError as exc:
            if state.format is OutputFormat.JSON:
                typer.echo(json.dumps(error_details(exc)), err=True)
            else:
                error_console.print(f"error: {exc}")
            code = next(
                (
                    exit_code
                    for error_type, exit_code in EXIT_CODES.items()
                    if isinstance(exc, error_type)
                ),
                1,
            )
            raise typer.Exit(code=code) from exc

    return invoke


@asynccontextmanager
async def client_for(
    room: str | None,
    ip: str | None,
    *,
    coordinator: bool = True,
) -> AsyncGenerator[SonosClient]:
    """Open a client for an explicit or configured target."""
    room, ip = resolve_target(room, ip)
    if room and not ip:
        ip = cached_ip(room)
        if ip:
            room = None
    controller = SonosController(timeout=state.timeout)
    async with await controller.client(room, ip=ip, coordinator=coordinator) as client:
        yield client
