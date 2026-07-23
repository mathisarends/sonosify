import asyncio

from sonosify import (
    AVTransportEvent,
    RenderingControlEvent,
    SonosController,
    SonosSystem,
)
from sonosify.cli._dependencies import Table, typer
from sonosify.cli.console import console
from sonosify.cli.output import print_object, print_records
from sonosify.cli.parameters import IpOpt, RoomArg
from sonosify.cli.runtime import async_command, client_for
from sonosify.cli.settings import resolve_target
from sonosify.cli.state import state


def register(app: typer.Typer) -> None:
    app.command()(discover)
    app.command(name="now-playing")(now_playing)
    app.command()(watch)


@async_command
async def discover() -> None:
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
async def now_playing(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Show what is currently playing on a speaker."""
    async with client_for(room, ip) as client:
        playback = await client.now_playing()
    track = playback.track
    data: dict[str, object] = {
        "state": playback.state or "UNKNOWN",
        "title": track.title if track else "",
        "artist": track.creator if track else "",
        "album": track.album if track else "",
        "position": playback.relative_time,
        "duration": playback.track_duration or (track.duration if track else ""),
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


@async_command
async def watch(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Stream live transport and volume events from a speaker."""
    try:
        target_room, target_ip = resolve_target(room, ip)
        controller = SonosController(timeout=state.timeout)
        async with controller.watch(target_room, ip=target_ip) as watcher:
            console.print(f"watching [cyan]{watcher.ip}[/]; press Ctrl+C to stop")
            async for event in watcher:
                match event:
                    case AVTransportEvent(transport_state=transport_state, track=track):
                        title = track.title if track else ""
                        console.print(f"transport {transport_state} {title}")
                    case RenderingControlEvent(volume=volume, muted=muted):
                        console.print(f"rendering volume={volume} muted={muted}")
                    case _:
                        console.print(f"{event.service} {event.values}")
    except asyncio.CancelledError:
        console.print("\nstopped watching")
