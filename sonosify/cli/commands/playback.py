import asyncio
from typing import Annotated

from sonosify import SonosClient, SonosController
from sonosify.cli._dependencies import typer
from sonosify.cli.output import print_action
from sonosify.cli.parameters import IpOpt, RoomArg, RoomOpt, target_room
from sonosify.cli.runtime import async_command, client_for
from sonosify.cli.state import state


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
    room: RoomOpt = None,
) -> None:
    """Resume playback on a speaker."""
    async with client_for(target_room(target, room), ip) as client:
        await client.play()
    print_action("[green]playing[/]", {"status": "playing"})


@async_command
async def pause(
    target: RoomArg = None,
    ip: IpOpt = None,
    room: RoomOpt = None,
    all_speakers: Annotated[
        bool, typer.Option("--all", help="Pause every group coordinator.")
    ] = False,
) -> None:
    """Pause playback on a speaker."""
    selected = target_room(target, room)
    if all_speakers:
        if selected or ip:
            raise typer.BadParameter("--all cannot be combined with a room or --ip")
        system = await SonosController(timeout=state.timeout).discover()

        async def pause_speaker(speaker) -> None:  # type: ignore[no-untyped-def]
            async with SonosClient.from_speaker(
                speaker, timeout=state.timeout
            ) as client:
                await client.pause()

        await asyncio.gather(
            *(
                pause_speaker(speaker)
                for speaker in system.speakers
                if speaker.is_coordinator
            )
        )
    else:
        async with client_for(selected, ip) as client:
            await client.pause()
    print_action("[yellow]paused[/]", {"status": "paused"})


@async_command
async def stop(target: RoomArg = None, ip: IpOpt = None, room: RoomOpt = None) -> None:
    """Stop playback on a speaker."""
    async with client_for(target_room(target, room), ip) as client:
        await client.stop()
    print_action("[yellow]stopped[/]", {"status": "stopped"})


@async_command
async def next(target: RoomArg = None, ip: IpOpt = None, room: RoomOpt = None) -> None:
    """Skip to the next track."""
    async with client_for(target_room(target, room), ip) as client:
        await client.next()
    print_action("[green]next[/]", {"status": "next"})


@async_command
async def previous(
    target: RoomArg = None, ip: IpOpt = None, room: RoomOpt = None
) -> None:
    """Skip to the previous track."""
    async with client_for(target_room(target, room), ip) as client:
        await client.previous()
    print_action("[green]previous[/]", {"status": "previous"})
