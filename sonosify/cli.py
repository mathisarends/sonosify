import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated

try:
    import typer
    from rich.console import Console
    from rich.table import Table
except ModuleNotFoundError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "The sonosify CLI requires the optional 'cli' dependencies. "
        "Install them with: pip install 'sonosify[cli]'"
    ) from exc

from sonosify import (
    AVTransportEvent,
    RenderingControlEvent,
    SonosClient,
    SonosController,
    SonosSystem,
)
from sonosify.errors import SonosifyError

app = typer.Typer(
    name="sonosify",
    help="Discover and control Sonos speakers from the command line.",
    no_args_is_help=True,
    add_completion=False,
)
favorites_app = typer.Typer(help="List and play Sonos favorites.", no_args_is_help=True)
app.add_typer(favorites_app, name="favorites")

console = Console()
err_console = Console(stderr=True, style="bold red")

RoomArg = Annotated[
    str | None,
    typer.Argument(
        help="Room name (or a unique substring). Optional when only one speaker is present.",
    ),
]
IpOpt = Annotated[
    str | None,
    typer.Option("--ip", help="Target a speaker by IP address instead of room name."),
]


def _run[T](coro: Awaitable[T]) -> T:
    """Run an async coroutine, turning library errors into clean CLI failures."""
    try:
        return asyncio.run(coro)
    except SonosifyError as exc:
        err_console.print(f"error: {exc}")
        raise typer.Exit(code=1) from exc


async def _with_client[T](
    room: str | None,
    ip: str | None,
    func: Callable[[SonosClient], Awaitable[T]],
    *,
    coordinator: bool = True,
) -> T:
    controller = SonosController()
    async with await controller.client(room, ip=ip, coordinator=coordinator) as client:
        return await func(client)


@app.command()
def discover() -> None:
    """List every Sonos speaker discovered on the local network."""
    system: SonosSystem = _run(SonosController().discover())
    if not system.speakers:
        console.print("No Sonos speakers found.")
        return

    table = Table(title="Sonos speakers")
    table.add_column("Room", style="cyan", no_wrap=True)
    table.add_column("IP", style="green")
    table.add_column("UID", style="dim")
    table.add_column("Coordinator", justify="center")
    for speaker in sorted(system.speakers, key=lambda s: s.room_name.casefold()):
        table.add_row(
            speaker.room_name or "?",
            speaker.ip,
            speaker.uid,
            "yes" if speaker.is_coordinator else "",
        )
    console.print(table)


@app.command()
def play(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Resume playback on a speaker."""
    _run(_with_client(room, ip, lambda c: c.play()))
    console.print("[green]playing[/]")


@app.command()
def pause(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Pause playback on a speaker."""
    _run(_with_client(room, ip, lambda c: c.pause()))
    console.print("[yellow]paused[/]")


@app.command()
def stop(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Stop playback on a speaker."""
    _run(_with_client(room, ip, lambda c: c.stop()))
    console.print("[yellow]stopped[/]")


@app.command()
def next(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Skip to the next track."""
    _run(_with_client(room, ip, lambda c: c.next()))
    console.print("[green]next[/]")


@app.command()
def previous(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Skip to the previous track."""
    _run(_with_client(room, ip, lambda c: c.previous()))
    console.print("[green]previous[/]")


@app.command()
def volume(
    room: RoomArg = None,
    level: Annotated[
        int | None, typer.Argument(help="Target volume (0-100). Omit to read the current volume.")
    ] = None,
    ip: IpOpt = None,
) -> None:
    """Get or set a speaker's volume."""
    if level is None:
        current = _run(_with_client(room, ip, lambda c: c.get_volume(), coordinator=False))
        console.print(f"volume: [cyan]{current}[/]")
    else:
        _run(_with_client(room, ip, lambda c: c.set_volume(level), coordinator=False))
        console.print(f"volume set to [cyan]{max(0, min(100, level))}[/]")


@app.command()
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

    muted = _run(_with_client(room, ip, action, coordinator=False))
    console.print("[yellow]muted[/]" if muted else "[green]unmuted[/]")


@app.command(name="now-playing")
def now_playing(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Show what is currently playing on a speaker."""
    state = _run(_with_client(room, ip, lambda c: c.now_playing()))
    track = state.track
    console.print(f"state: [cyan]{state.state or 'UNKNOWN'}[/]")
    if track and track.title:
        console.print(f"title: {track.title}")
        if track.creator:
            console.print(f"artist: {track.creator}")
        if track.album:
            console.print(f"album: {track.album}")
        position = state.relative_time or "?"
        duration = state.track_duration or track.duration or "?"
        console.print(f"position: {position} / {duration}")
    else:
        console.print("[dim]nothing playing[/]")


@app.command()
def queue(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Show the playback queue of a speaker."""
    tracks = _run(_with_client(room, ip, lambda c: c.queue()))
    if not tracks:
        console.print("[dim]queue is empty[/]")
        return

    table = Table(title="Queue")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Title", style="cyan")
    for track in tracks:
        table.add_row(str(track.position or ""), track.title or track.uri)
    console.print(table)


@favorites_app.command("list")
def favorites_list(room: RoomArg = None, ip: IpOpt = None) -> None:
    """List the Sonos favorites available to a speaker."""
    favorites = _run(_with_client(room, ip, lambda c: c.favorites()))
    if not favorites:
        console.print("[dim]no favorites[/]")
        return

    table = Table(title="Favorites")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Title", style="cyan")
    for index, favorite in enumerate(favorites, start=1):
        table.add_row(str(index), favorite.title)
    console.print(table)


@favorites_app.command("play")
def favorites_play(
    name: Annotated[str, typer.Argument(help="Favorite title (or a unique substring).")],
    room: RoomArg = None,
    ip: IpOpt = None,
) -> None:
    """Play a favorite by name on a speaker."""

    async def action(client: SonosClient) -> str:
        favorites = await client.favorites()
        needle = name.casefold()
        matches = [f for f in favorites if needle in f.title.casefold()]
        if not matches:
            raise SonosifyError(f"no favorite matching {name!r}")
        if len(matches) > 1:
            titles = ", ".join(f.title for f in matches)
            raise SonosifyError(f"ambiguous favorite {name!r}; matches: {titles}")
        await client.open_favorite(matches[0])
        return matches[0].title

    title = _run(_with_client(room, ip, action))
    console.print(f"[green]playing favorite[/] {title}")


@app.command()
def spotify(
    uri: Annotated[str, typer.Argument(help="Spotify URI or share URL.")],
    room: RoomArg = None,
    ip: IpOpt = None,
    play_now: Annotated[
        bool, typer.Option("--next/--queue", help="Enqueue as the next track instead of last.")
    ] = False,
) -> None:
    """Enqueue a Spotify track, album, or playlist on a speaker."""
    _run(_with_client(room, ip, lambda c: c.open_spotify(uri, next_=play_now)))
    console.print(f"[green]enqueued[/] {uri}")


@app.command()
def watch(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Stream live transport and volume events from a speaker."""

    async def stream() -> None:
        controller = SonosController()
        async with controller.watch(room, ip=ip) as watcher:
            console.print(f"watching [cyan]{watcher.ip}[/]; press Ctrl+C to stop")
            async for event in watcher:
                match event:
                    case AVTransportEvent(transport_state=state, track=track):
                        title = track.title if track else ""
                        console.print(f"transport {state} {title}")
                    case RenderingControlEvent(volume=volume, muted=muted):
                        console.print(f"rendering volume={volume} muted={muted}")
                    case _:
                        console.print(f"{event.service} {event.values}")

    try:
        _run(stream())
    except KeyboardInterrupt:
        console.print("\nstopped watching")


if __name__ == "__main__":
    app()
