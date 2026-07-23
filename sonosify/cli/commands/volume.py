import asyncio
from typing import Annotated

from sonosify import SonosClient, SonosController
from sonosify.cli._dependencies import typer
from sonosify.cli.console import console
from sonosify.cli.output import print_action, print_object
from sonosify.cli.parameters import IpOpt, RoomArg, RoomOpt, target_room
from sonosify.cli.runtime import async_command, client_for
from sonosify.cli.state import state


def register(app: typer.Typer) -> None:
    app.command()(volume)
    app.command(name="volume-up")(volume_up)
    app.command(name="volume-down")(volume_down)
    app.command(name="get-volume")(get_volume)
    app.command(name="set-volume")(set_volume)
    app.command()(mute)


@async_command
async def volume(
    target: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Room name, or target volume when using the configured "
                "default speaker. Omit to read the current volume."
            ),
        ),
    ] = None,
    level: Annotated[
        int | None,
        typer.Argument(help="Target volume (0-100). Omit to read the current volume."),
    ] = None,
    ip: IpOpt = None,
    room_option: RoomOpt = None,
) -> None:
    """Get or set a speaker's volume."""
    room = target_room(target, room_option)
    if level is None and target is not None:
        try:
            level = int(target)
            room = None
        except ValueError:
            pass

    if level is None:
        async with client_for(room, ip, coordinator=False) as client:
            current = await client.get_volume()
        print_object(
            {"volume": current}, lambda: console.print(f"volume: [cyan]{current}[/]")
        )
    else:
        async with client_for(room, ip, coordinator=False) as client:
            await client.set_volume(level)
        clamped = max(0, min(100, level))
        print_action(f"volume set to [cyan]{clamped}[/]", {"volume": clamped})


@async_command
async def volume_up(
    target: RoomArg = None,
    amount: Annotated[
        int, typer.Argument(help="Percentage points to raise the volume by.")
    ] = 5,
    ip: IpOpt = None,
    room: RoomOpt = None,
) -> None:
    """Raise a speaker's volume by a number of percentage points."""
    async with client_for(target_room(target, room), ip, coordinator=False) as client:
        new_level = await client.adjust_volume(amount)
    print_action(f"volume [green]{new_level}[/]", {"volume": new_level})


@async_command
async def volume_down(
    target: RoomArg = None,
    amount: Annotated[
        int, typer.Argument(help="Percentage points to lower the volume by.")
    ] = 5,
    ip: IpOpt = None,
    room: RoomOpt = None,
) -> None:
    """Lower a speaker's volume by a number of percentage points."""
    async with client_for(target_room(target, room), ip, coordinator=False) as client:
        new_level = await client.adjust_volume(-amount)
    print_action(f"volume [yellow]{new_level}[/]", {"volume": new_level})


@async_command
async def mute(
    target: RoomArg = None,
    on: Annotated[
        bool | None,
        typer.Option("--on/--off", help="Force mute on or off. Omit to toggle."),
    ] = None,
    ip: IpOpt = None,
    room: RoomOpt = None,
) -> None:
    """Mute, unmute, or toggle mute on a speaker."""
    async with client_for(target_room(target, room), ip, coordinator=False) as client:
        if on is None:
            muted = await client.toggle_mute()
        else:
            await client.set_mute(on)
            muted = on
    print_action(
        "[yellow]muted[/]" if muted else "[green]unmuted[/]",
        {"muted": muted},
    )


@async_command
async def get_volume(
    target: RoomArg = None, ip: IpOpt = None, room: RoomOpt = None
) -> None:
    """Read volume with unambiguous argument parsing."""
    async with client_for(target_room(target, room), ip, coordinator=False) as client:
        current = await client.get_volume()
    print_object(
        {"volume": current}, lambda: console.print(f"volume: [cyan]{current}[/]")
    )


@async_command
async def set_volume(
    level: Annotated[int, typer.Argument(min=0, max=100, help="Target volume.")],
    target: RoomArg = None,
    ip: IpOpt = None,
    room: RoomOpt = None,
    group: Annotated[
        str | None,
        typer.Option("--group", help="Set every member of the named group."),
    ] = None,
) -> None:
    """Set volume with optional group targeting."""
    selected = target_room(target, room)
    targets: list[str] = []
    if group:
        if selected or ip:
            raise typer.BadParameter("--group cannot be combined with a room or --ip")
        system = await SonosController(timeout=state.timeout).discover()
        matching = [
            item
            for item in system.groups
            if item.id.casefold() == group.casefold()
            or (
                item.coordinator
                and item.coordinator.room_name.casefold() == group.casefold()
            )
        ]
        if len(matching) != 1:
            raise typer.BadParameter(f"group {group!r} was not found or is ambiguous")

        async def apply(speaker) -> None:  # type: ignore[no-untyped-def]
            async with SonosClient.from_speaker(
                speaker, timeout=state.timeout
            ) as client:
                await client.set_volume(level)

        targets = [speaker.room_name for speaker in matching[0].members]
        await asyncio.gather(*(apply(speaker) for speaker in matching[0].members))
    else:
        async with client_for(selected, ip, coordinator=False) as client:
            await client.set_volume(level)
    print_action(
        f"volume set to [cyan]{level}[/]",
        {"volume": level, "targets": targets},
    )
