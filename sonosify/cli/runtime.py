import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any

from sonosify import SonosClient, SonosController
from sonosify.cli._dependencies import typer
from sonosify.cli.console import error_console
from sonosify.cli.settings import resolve_target
from sonosify.cli.state import state
from sonosify.errors import SonosifyError


def async_command[**P, T](
    function: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, T]:
    """Adapt an async command handler to Typer's synchronous callback API."""

    @wraps(function)
    def invoke(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return asyncio.run(function(*args, **kwargs))
        except SonosifyError as exc:
            error_console.print(f"error: {exc}")
            raise typer.Exit(code=1) from exc

    return invoke


@asynccontextmanager
async def client_for(
    room: str | None,
    ip: str | None,
    *,
    coordinator: bool = True,
) -> AsyncIterator[SonosClient]:
    """Open a client for an explicit or configured target."""
    room, ip = resolve_target(room, ip)
    controller = SonosController(timeout=state.timeout)
    async with await controller.client(room, ip=ip, coordinator=coordinator) as client:
        yield client
