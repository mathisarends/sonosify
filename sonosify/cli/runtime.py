import asyncio
from collections.abc import Awaitable, Callable

from sonosify import SonosClient, SonosController
from sonosify.cli._dependencies import typer
from sonosify.cli.console import error_console
from sonosify.cli.settings import resolve_target
from sonosify.cli.state import state
from sonosify.errors import SonosifyError


def run[T](coroutine: Awaitable[T]) -> T:
    """Run an async operation and turn library errors into clean CLI failures."""
    try:
        return asyncio.run(coroutine)
    except SonosifyError as exc:
        error_console.print(f"error: {exc}")
        raise typer.Exit(code=1) from exc


async def with_client[T](
    room: str | None,
    ip: str | None,
    operation: Callable[[SonosClient], Awaitable[T]],
    *,
    coordinator: bool = True,
) -> T:
    """Open a client for an explicit or configured target and run an operation."""
    room, ip = resolve_target(room, ip)
    controller = SonosController(timeout=state.timeout)
    async with await controller.client(room, ip=ip, coordinator=coordinator) as client:
        return await operation(client)
