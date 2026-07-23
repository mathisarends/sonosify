from typing import Annotated

from sonosify import RepeatMode
from sonosify.cli._dependencies import typer
from sonosify.cli.commands.discovery import duration_seconds
from sonosify.cli.output import print_action
from sonosify.cli.parameters import IpOpt, RoomArg, RoomOpt, target_room
from sonosify.cli.runtime import async_command, client_for


def register(app: typer.Typer) -> None:
    app.command()(seek)
    app.command()(shuffle)
    app.command()(repeat)
    app.command()(crossfade)
    app.command()(sleep)


def _hms(seconds: float) -> str:
    rounded = int(seconds)
    hours, remainder = divmod(rounded, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}"


@async_command
async def seek(
    position: Annotated[str, typer.Argument(help="Track position (for example 1:30).")],
    room: RoomArg = None,
    ip: IpOpt = None,
    room_option: RoomOpt = None,
) -> None:
    """Seek within the current track."""
    parts = position.split(":")
    if not all(part.isdigit() for part in parts) or len(parts) not in {2, 3}:
        raise typer.BadParameter("position must be MM:SS or H:MM:SS")
    values = [int(part) for part in parts]
    if len(values) == 2:
        values.insert(0, 0)
    normalized = f"{values[0]}:{values[1]:02d}:{values[2]:02d}"
    async with client_for(target_room(room, room_option), ip) as client:
        await client.seek(normalized)
    print_action(f"[green]seeked[/] to {normalized}", {"position": normalized})


@async_command
async def shuffle(
    enabled: Annotated[bool, typer.Argument(help="Whether shuffle is on or off.")],
    room: RoomArg = None,
    ip: IpOpt = None,
    room_option: RoomOpt = None,
) -> None:
    """Enable or disable shuffle while preserving repeat mode."""
    async with client_for(target_room(room, room_option), ip) as client:
        play_mode = await client.set_shuffle(enabled)
    print_action(
        f"shuffle {'[green]on[/]' if enabled else '[yellow]off[/]'}",
        {"shuffle": enabled, "play_mode": play_mode},
    )


@async_command
async def repeat(
    mode: Annotated[RepeatMode, typer.Argument(help="Repeat mode: off, one, or all.")],
    room: RoomArg = None,
    ip: IpOpt = None,
    room_option: RoomOpt = None,
) -> None:
    """Set repeat mode while preserving shuffle."""
    async with client_for(target_room(room, room_option), ip) as client:
        play_mode = await client.set_repeat(mode)
    print_action(
        f"repeat [cyan]{mode.value}[/]",
        {"repeat": mode.value, "play_mode": play_mode},
    )


@async_command
async def crossfade(
    enabled: Annotated[bool, typer.Argument(help="Whether crossfade is on or off.")],
    room: RoomArg = None,
    ip: IpOpt = None,
    room_option: RoomOpt = None,
) -> None:
    """Enable or disable crossfade."""
    async with client_for(target_room(room, room_option), ip) as client:
        await client.set_crossfade(enabled)
    print_action(
        f"crossfade {'[green]on[/]' if enabled else '[yellow]off[/]'}",
        {"crossfade": enabled},
    )


@async_command
async def sleep(
    duration: Annotated[
        str, typer.Argument(help="Timer duration such as 30m, or 'off'.")
    ],
    room: RoomArg = None,
    ip: IpOpt = None,
    room_option: RoomOpt = None,
) -> None:
    """Configure or disable the sleep timer."""
    target = None
    if duration.casefold() != "off":
        seconds = duration_seconds(duration)
        if seconds is None:
            raise typer.BadParameter("duration is required")
        target = _hms(seconds)
    async with client_for(target_room(room, room_option), ip) as client:
        await client.configure_sleep_timer(target)
    print_action(
        "[green]sleep timer set[/]" if target else "[green]sleep timer disabled[/]",
        {"sleep_timer": target},
    )
