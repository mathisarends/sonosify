from typing import Annotated

from sonosify import SonosClient
from sonosify.cli._dependencies import typer
from sonosify.cli.console import console
from sonosify.cli.output import print_action, print_object
from sonosify.cli.parameters import IpOpt, RoomArg
from sonosify.cli.runtime import run, with_client


def register(app: typer.Typer) -> None:
    app.command()(volume)
    app.command(name="volume-up")(volume_up)
    app.command(name="volume-down")(volume_down)
    app.command()(mute)


def volume(
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
        current = run(
            with_client(room, ip, lambda client: client.get_volume(), coordinator=False)
        )
        print_object(
            {"volume": current}, lambda: console.print(f"volume: [cyan]{current}[/]")
        )
    else:
        run(
            with_client(
                room,
                ip,
                lambda client: client.set_volume(level),
                coordinator=False,
            )
        )
        clamped = max(0, min(100, level))
        print_action(f"volume set to [cyan]{clamped}[/]", {"volume": clamped})


async def adjust_volume(client: SonosClient, delta: int) -> int:
    new_level = max(0, min(100, await client.get_volume() + delta))
    await client.set_volume(new_level)
    return new_level


def volume_up(
    room: RoomArg = None,
    amount: Annotated[
        int, typer.Argument(help="Percentage points to raise the volume by.")
    ] = 5,
    ip: IpOpt = None,
) -> None:
    """Raise a speaker's volume by a number of percentage points."""
    new_level = run(
        with_client(
            room,
            ip,
            lambda client: adjust_volume(client, amount),
            coordinator=False,
        )
    )
    print_action(f"volume [green]{new_level}[/]", {"volume": new_level})


def volume_down(
    room: RoomArg = None,
    amount: Annotated[
        int, typer.Argument(help="Percentage points to lower the volume by.")
    ] = 5,
    ip: IpOpt = None,
) -> None:
    """Lower a speaker's volume by a number of percentage points."""
    new_level = run(
        with_client(
            room,
            ip,
            lambda client: adjust_volume(client, -amount),
            coordinator=False,
        )
    )
    print_action(f"volume [yellow]{new_level}[/]", {"volume": new_level})


def mute(
    room: RoomArg = None,
    on: Annotated[
        bool | None,
        typer.Option("--on/--off", help="Force mute on or off. Omit to toggle."),
    ] = None,
    ip: IpOpt = None,
) -> None:
    """Mute, unmute, or toggle mute on a speaker."""

    async def action(client: SonosClient) -> bool:
        if on is None:
            return await client.toggle_mute()
        await client.set_mute(on)
        return on

    muted = run(with_client(room, ip, action, coordinator=False))
    print_action(
        "[yellow]muted[/]" if muted else "[green]unmuted[/]",
        {"muted": muted},
    )
