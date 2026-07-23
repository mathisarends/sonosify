import asyncio
import json
import re
from contextlib import suppress
from typing import Annotated

from sonosify import SonosController, SonosSystem
from sonosify.cli._dependencies import Table, typer
from sonosify.cli.console import console
from sonosify.cli.output import print_object, print_records
from sonosify.cli.parameters import IpOpt, RoomArg, RoomOpt, target_room
from sonosify.cli.runtime import async_command, client_for
from sonosify.cli.settings import resolve_target, save_speaker_cache
from sonosify.cli.state import OutputFormat, state


def register(app: typer.Typer) -> None:
    app.command()(discover)
    app.command(name="now-playing")(now_playing)
    app.command()(status)
    app.command()(watch)


@async_command
async def discover(
    refresh: bool = typer.Option(
        False, "--refresh", help="Force discovery and refresh the speaker cache."
    ),
) -> None:
    """List every Sonos speaker discovered on the local network."""
    system: SonosSystem = await SonosController(timeout=state.timeout).discover()
    speakers = sorted(system.speakers, key=lambda speaker: speaker.room_name.casefold())
    records: list[dict[str, object]] = [
        {
            "room": speaker.room_name or "?",
            "ip": speaker.ip,
            "uid": speaker.uid,
            "coordinator": speaker.is_coordinator,
        }
        for speaker in speakers
    ]
    save_speaker_cache(records)

    def plain() -> None:
        if not records:
            console.print("No Sonos speakers found.")
            return
        table = Table(title="Sonos speakers")
        table.add_column("Room", style="cyan", no_wrap=True)
        table.add_column("IP", style="green")
        table.add_column("UID", style="dim")
        table.add_column("Coordinator", justify="center")
        for record in records:
            table.add_row(
                str(record["room"]),
                str(record["ip"]),
                str(record["uid"]),
                "yes" if record["coordinator"] else "",
            )
        console.print(table)

    print_records(records, ["room", "ip", "uid", "coordinator"], plain)


@async_command
async def now_playing(
    target: RoomArg = None, ip: IpOpt = None, room: RoomOpt = None
) -> None:
    """Show what is currently playing on a speaker."""
    async with client_for(target_room(target, room), ip) as client:
        playback = await client.now_playing()
    track = playback.track
    data: dict[str, object] = {
        "state": playback.state or "UNKNOWN",
        "title": track.title if track else "",
        "artist": track.creator if track else "",
        "album": track.album if track else "",
        "position": playback.relative_time,
        "duration": playback.track_duration or (track.duration if track else ""),
        "position_s": time_seconds(playback.relative_time),
        "duration_s": time_seconds(
            playback.track_duration or (track.duration if track else "")
        ),
    }

    def plain() -> None:
        console.print(f"state: [cyan]{data['state']}[/]")
        if track and track.title:
            console.print(f"title: {track.title}")
            if track.creator:
                console.print(f"artist: {track.creator}")
            if track.album:
                console.print(f"album: {track.album}")
            console.print(
                f"position: {data['position'] or '?'} / {data['duration'] or '?'}"
            )
        else:
            console.print("[dim]nothing playing[/]")

    print_object(data, plain)


def time_seconds(value: str) -> int:
    parts = value.split(":")
    if not value or not all(part.isdigit() for part in parts):
        return 0
    return sum(int(part) * 60**index for index, part in enumerate(reversed(parts)))


def duration_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h)?", value.strip())
    if not match:
        raise typer.BadParameter("duration must look like 500ms, 10s, 2m, or 1h")
    amount = float(match.group(1))
    return amount * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}.get(
        match.group(2) or "s", 1
    )


@async_command
async def status(
    target: RoomArg = None, ip: IpOpt = None, room: RoomOpt = None
) -> None:
    """Return playback, volume, and mute state in one request."""
    async with client_for(target_room(target, room), ip) as client:
        playback, volume, muted = await asyncio.gather(
            client.now_playing(),
            client.get_volume(),
            client.get_mute(),
        )
        track = playback.track
        duration = playback.track_duration or (track.duration if track else "")
        data: dict[str, object] = {
            "state": playback.state or "UNKNOWN",
            "volume": volume,
            "muted": muted,
            "track": track.model_dump() if track else None,
            "group": client.uid,
            "position": playback.relative_time,
            "duration": duration,
            "position_s": time_seconds(playback.relative_time),
            "duration_s": time_seconds(duration),
        }

    def plain() -> None:
        console.print(f"state: [cyan]{data['state']}[/]")
        console.print(f"volume: [cyan]{volume}[/] muted: {muted}")
        if track:
            console.print(f"track: {track.title or track.uri}")

    print_object(data, plain)


@async_command
async def watch(
    target: RoomArg = None,
    ip: IpOpt = None,
    room: RoomOpt = None,
    count: Annotated[
        int | None, typer.Option("--count", min=1, help="Stop after N events.")
    ] = None,
    duration: Annotated[
        str | None,
        typer.Option("--duration", help="Stop after a duration such as 10s."),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option("--until", help="Stop when this transport state is observed."),
    ] = None,
) -> None:
    """Stream live transport and volume events from a speaker."""
    limit = duration_seconds(duration)

    async def consume() -> None:
        selected_room, target_ip = resolve_target(target_room(target, room), ip)
        controller = SonosController(timeout=state.timeout)
        async with controller.watch(selected_room, ip=target_ip) as watcher:
            typer.echo(f"watching {watcher.ip}", err=True)
            seen = 0
            async for event in watcher:
                seen += 1
                data = event.model_dump(mode="json")
                if state.format is OutputFormat.JSON:
                    typer.echo(json.dumps({"schema_version": 1, **data}))
                else:
                    if event.service == "av_transport":
                        console.print(
                            f"transport {getattr(event, 'transport_state', None)} "
                            f"{getattr(getattr(event, 'track', None), 'title', '')}"
                        )
                    elif event.service == "rendering_control":
                        console.print(
                            f"rendering volume={getattr(event, 'volume', None)} "
                            f"muted={getattr(event, 'muted', None)}"
                        )
                    else:
                        console.print(f"{event.service} {data}")
                event_state = getattr(event, "transport_state", None)
                if count is not None and seen >= count:
                    break
                if (
                    until
                    and event_state
                    and event_state.value.casefold() == until.casefold()
                ):
                    break

    try:
        if limit is None:
            await consume()
        else:
            async with asyncio.timeout(limit):
                await consume()
    except TimeoutError:
        pass
    except asyncio.CancelledError:
        with suppress(Exception):
            typer.echo("stopped watching", err=True)
