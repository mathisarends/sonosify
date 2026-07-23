from typing import Annotated

from sonosify.cli._dependencies import typer
from sonosify.cli.output import print_action
from sonosify.cli.parameters import IpOpt, RoomArg
from sonosify.cli.runtime import async_command, client_for


def register(app: typer.Typer) -> None:
    app.command()(play)
    app.command()(pause)
    app.command()(stop)
    app.command()(next)
    app.command()(previous)


@async_command
async def play(
    target: Annotated[
        str | None,
        typer.Argument(help="Room name. Falls back to the configured default speaker."),
    ] = None,
    ip: IpOpt = None,
) -> None:
    """Resume playback on a speaker."""
    async with client_for(target, ip) as client:
        await client.play()
    print_action("[green]playing[/]", {"status": "playing"})


@async_command
async def pause(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Pause playback on a speaker."""
    async with client_for(room, ip) as client:
        await client.pause()
    print_action("[yellow]paused[/]", {"status": "paused"})


@async_command
async def stop(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Stop playback on a speaker."""
    async with client_for(room, ip) as client:
        await client.stop()
    print_action("[yellow]stopped[/]", {"status": "stopped"})


@async_command
async def next(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Skip to the next track."""
    async with client_for(room, ip) as client:
        await client.next()
    print_action("[green]next[/]", {"status": "next"})


@async_command
async def previous(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Skip to the previous track."""
    async with client_for(room, ip) as client:
        await client.previous()
    print_action("[green]previous[/]", {"status": "previous"})
