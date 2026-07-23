from typing import Annotated

from sonosify.cli._dependencies import typer
from sonosify.cli.console import console
from sonosify.cli.output import print_action, print_object
from sonosify.cli.parameters import IpOpt, RoomArg
from sonosify.cli.runtime import async_command, client_for


def register(app: typer.Typer) -> None:
    app.command()(volume)
    app.command(name="volume-up")(volume_up)
    app.command(name="volume-down")(volume_down)
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
) -> None:
    """Get or set a speaker's volume."""
    room = target
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
    room: RoomArg = None,
    amount: Annotated[
        int, typer.Argument(help="Percentage points to raise the volume by.")
    ] = 5,
    ip: IpOpt = None,
) -> None:
    """Raise a speaker's volume by a number of percentage points."""
    async with client_for(room, ip, coordinator=False) as client:
        new_level = await client.adjust_volume(amount)
    print_action(f"volume [green]{new_level}[/]", {"volume": new_level})


@async_command
async def volume_down(
    room: RoomArg = None,
    amount: Annotated[
        int, typer.Argument(help="Percentage points to lower the volume by.")
    ] = 5,
    ip: IpOpt = None,
) -> None:
    """Lower a speaker's volume by a number of percentage points."""
    async with client_for(room, ip, coordinator=False) as client:
        new_level = await client.adjust_volume(-amount)
    print_action(f"volume [yellow]{new_level}[/]", {"volume": new_level})


@async_command
async def mute(
    room: RoomArg = None,
    on: Annotated[
        bool | None,
        typer.Option("--on/--off", help="Force mute on or off. Omit to toggle."),
    ] = None,
    ip: IpOpt = None,
) -> None:
    """Mute, unmute, or toggle mute on a speaker."""
    async with client_for(room, ip, coordinator=False) as client:
        if on is None:
            muted = await client.toggle_mute()
        else:
            await client.set_mute(on)
            muted = on
    print_action(
        "[yellow]muted[/]" if muted else "[green]unmuted[/]",
        {"muted": muted},
    )
