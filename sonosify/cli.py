import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
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
from sonosify.client import DEFAULT_TIMEOUT
from sonosify.errors import SonosifyError


class OutputFormat(StrEnum):
    PLAIN = "plain"
    JSON = "json"
    TSV = "tsv"


class _State:
    format: OutputFormat = OutputFormat.PLAIN
    debug: bool = False
    timeout: float = DEFAULT_TIMEOUT


state = _State()

CONFIG_PATH = Path(typer.get_app_dir("sonosify")) / "config.json"

app = typer.Typer(
    name="sonosify",
    help="Discover and control Sonos speakers from the command line.",
    no_args_is_help=True,
    add_completion=False,
)
favorites_app = typer.Typer(help="List and play Sonos favorites.", no_args_is_help=True)
config_app = typer.Typer(help="Manage local CLI defaults (e.g. the default speaker).")
app.add_typer(favorites_app, name="favorites")
app.add_typer(config_app, name="config")

console = Console()
err_console = Console(stderr=True, style="bold red")

RoomArg = Annotated[
    str | None,
    typer.Argument(
        help="Room name (or a unique substring). Falls back to the configured default speaker.",
    ),
]
IpOpt = Annotated[
    str | None,
    typer.Option("--ip", help="Target a speaker by IP address instead of room name."),
]


# --------------------------------------------------------------------------- config


def load_config() -> dict[str, object]:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))  # type: ignore[return-value]
    except OSError, json.JSONDecodeError:
        return {}


def save_config(config: dict[str, object]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _resolve_target(room: str | None, ip: str | None) -> tuple[str | None, str | None]:
    """Apply the configured default speaker when no explicit target is given."""
    if room or ip:
        return room, ip
    config = load_config()
    return config.get("default_room") or None, config.get("default_ip") or None  # type: ignore[return-value]


# --------------------------------------------------------------------------- output


def _print_action(message: str, data: dict[str, object]) -> None:
    match state.format:
        case OutputFormat.JSON:
            typer.echo(json.dumps(data))
        case OutputFormat.TSV:
            typer.echo("\t".join(str(value) for value in data.values()))
        case _:
            console.print(message)


def _print_object(data: dict[str, object], plain: Callable[[], None]) -> None:
    match state.format:
        case OutputFormat.JSON:
            typer.echo(json.dumps(data))
        case OutputFormat.TSV:
            for key, value in data.items():
                typer.echo(f"{key}\t{value}")
        case _:
            plain()


def _print_records(
    records: list[dict[str, object]],
    headers: list[str],
    plain: Callable[[], None],
) -> None:
    match state.format:
        case OutputFormat.JSON:
            typer.echo(json.dumps(records))
        case OutputFormat.TSV:
            typer.echo("\t".join(headers))
            for record in records:
                typer.echo("\t".join(str(record.get(h, "")) for h in headers))
        case _:
            plain()


# --------------------------------------------------------------------------- runtime


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
    room, ip = _resolve_target(room, ip)
    controller = SonosController(timeout=state.timeout)
    async with await controller.client(room, ip=ip, coordinator=coordinator) as client:
        return await func(client)


@app.callback()
def main(
    output_format: Annotated[
        OutputFormat | None,
        typer.Option("--format", help="Output format for machine-readable scripting."),
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="SOAP / discovery timeout in seconds."),
    ] = None,
    debug: Annotated[
        bool, typer.Option("--debug", help="Print SOAP request/response traces to stderr.")
    ] = False,
) -> None:
    """Discover and control Sonos speakers from the command line."""
    config = load_config()
    state.format = output_format or OutputFormat(config.get("default_format", OutputFormat.PLAIN))
    state.timeout = (
        timeout if timeout is not None else float(config.get("default_timeout", DEFAULT_TIMEOUT))
    )
    state.debug = debug
    if debug:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
        sonos_logger = logging.getLogger("sonosify")
        sonos_logger.setLevel(logging.DEBUG)
        sonos_logger.addHandler(handler)


# --------------------------------------------------------------------------- discovery


@app.command()
def discover() -> None:
    """List every Sonos speaker discovered on the local network."""
    system: SonosSystem = _run(SonosController(timeout=state.timeout).discover())
    speakers = sorted(system.speakers, key=lambda s: s.room_name.casefold())
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

    _print_records(records, ["room", "ip", "uid", "coordinator"], plain)


@app.command(name="now-playing")
def now_playing(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Show what is currently playing on a speaker."""
    playback = _run(_with_client(room, ip, lambda c: c.now_playing()))
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
            console.print(f"position: {data['position'] or '?'} / {data['duration'] or '?'}")
        else:
            console.print("[dim]nothing playing[/]")

    _print_object(data, plain)


@app.command()
def watch(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Stream live transport and volume events from a speaker."""

    async def stream() -> None:
        target_room, target_ip = _resolve_target(room, ip)
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

    try:
        _run(stream())
    except KeyboardInterrupt:
        console.print("\nstopped watching")


# --------------------------------------------------------------------------- playback


@app.command()
def play(
    target: Annotated[
        str | None,
        typer.Argument(help="Room name. Falls back to the configured default speaker."),
    ] = None,
    ip: IpOpt = None,
) -> None:
    """Resume playback on a speaker."""
    _run(_with_client(target, ip, lambda c: c.play()))
    _print_action("[green]playing[/]", {"status": "playing"})


@app.command()
def pause(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Pause playback on a speaker."""
    _run(_with_client(room, ip, lambda c: c.pause()))
    _print_action("[yellow]paused[/]", {"status": "paused"})


@app.command()
def stop(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Stop playback on a speaker."""
    _run(_with_client(room, ip, lambda c: c.stop()))
    _print_action("[yellow]stopped[/]", {"status": "stopped"})


@app.command()
def next(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Skip to the next track."""
    _run(_with_client(room, ip, lambda c: c.next()))
    _print_action("[green]next[/]", {"status": "next"})


@app.command()
def previous(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Skip to the previous track."""
    _run(_with_client(room, ip, lambda c: c.previous()))
    _print_action("[green]previous[/]", {"status": "previous"})


# --------------------------------------------------------------------------- volume & mute


@app.command()
def volume(
    target: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Room name, or target volume when using the configured default speaker. "
                "Omit to read the current volume."
            ),
        ),
    ] = None,
    level: Annotated[
        int | None, typer.Argument(help="Target volume (0-100). Omit to read the current volume.")
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
        current = _run(_with_client(room, ip, lambda c: c.get_volume(), coordinator=False))
        _print_object({"volume": current}, lambda: console.print(f"volume: [cyan]{current}[/]"))
    else:
        _run(_with_client(room, ip, lambda c: c.set_volume(level), coordinator=False))
        clamped = max(0, min(100, level))
        _print_action(f"volume set to [cyan]{clamped}[/]", {"volume": clamped})


async def _adjust_volume(client: SonosClient, delta: int) -> int:
    new_level = max(0, min(100, await client.get_volume() + delta))
    await client.set_volume(new_level)
    return new_level


@app.command(name="volume-up")
def volume_up(
    room: RoomArg = None,
    amount: Annotated[int, typer.Argument(help="Percentage points to raise the volume by.")] = 5,
    ip: IpOpt = None,
) -> None:
    """Raise a speaker's volume by a number of percentage points."""
    new_level = _run(_with_client(room, ip, lambda c: _adjust_volume(c, amount), coordinator=False))
    _print_action(f"volume [green]{new_level}[/]", {"volume": new_level})


@app.command(name="volume-down")
def volume_down(
    room: RoomArg = None,
    amount: Annotated[int, typer.Argument(help="Percentage points to lower the volume by.")] = 5,
    ip: IpOpt = None,
) -> None:
    """Lower a speaker's volume by a number of percentage points."""
    new_level = _run(
        _with_client(room, ip, lambda c: _adjust_volume(c, -amount), coordinator=False)
    )
    _print_action(f"volume [yellow]{new_level}[/]", {"volume": new_level})


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
    _print_action(
        "[yellow]muted[/]" if muted else "[green]unmuted[/]",
        {"muted": muted},
    )


# --------------------------------------------------------------------------- queue


@app.command()
def queue(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Show the playback queue of a speaker."""
    tracks = _run(_with_client(room, ip, lambda c: c.queue()))
    records: list[dict[str, object]] = [
        {"position": track.position or "", "title": track.title or track.uri} for track in tracks
    ]

    def plain() -> None:
        if not records:
            console.print("[dim]queue is empty[/]")
            return
        table = Table(title="Queue")
        table.add_column("#", justify="right", style="dim")
        table.add_column("Title", style="cyan")
        for record in records:
            table.add_row(str(record["position"]), str(record["title"]))
        console.print(table)

    _print_records(records, ["position", "title"], plain)


@app.command()
def enqueue(
    uri: Annotated[str, typer.Argument(help="URI to add to the Sonos queue.")],
    room: Annotated[
        str | None,
        typer.Option("--room", "-r", help="Target room (falls back to the default speaker)."),
    ] = None,
    ip: IpOpt = None,
    play_next: Annotated[
        bool, typer.Option("--next/--queue", help="Enqueue as the next track instead of last.")
    ] = False,
    play_now: Annotated[
        bool, typer.Option("--play", help="Start playback at the enqueued queue position.")
    ] = False,
) -> None:
    """Add a URI to the speaker queue."""
    position = _run(
        _with_client(room, ip, lambda c: c.enqueue_uri(uri, next_=play_next, play=play_now))
    )
    status = "playing" if play_now else "enqueued"
    _print_action(
        f"[green]{status}[/] {uri}",
        {"status": status, "uri": uri, "position": position or ""},
    )


# --------------------------------------------------------------------------- favorites


@favorites_app.command("list")
def favorites_list(room: RoomArg = None, ip: IpOpt = None) -> None:
    """List the Sonos favorites available to a speaker."""
    favorites = _run(_with_client(room, ip, lambda c: c.favorites()))
    records: list[dict[str, object]] = [
        {"index": index, "title": favorite.title}
        for index, favorite in enumerate(favorites, start=1)
    ]

    def plain() -> None:
        if not records:
            console.print("[dim]no favorites[/]")
            return
        table = Table(title="Favorites")
        table.add_column("#", justify="right", style="dim")
        table.add_column("Title", style="cyan")
        for record in records:
            table.add_row(str(record["index"]), str(record["title"]))
        console.print(table)

    _print_records(records, ["index", "title"], plain)


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
    _print_action(f"[green]playing favorite[/] {title}", {"status": "playing", "favorite": title})


# --------------------------------------------------------------------------- open / track


@app.command()
def open(
    value: Annotated[str, typer.Argument(help="Stream URL or playable Sonos URI.")],
    room: Annotated[
        str | None,
        typer.Option("--room", "-r", help="Target room (falls back to the default speaker)."),
    ] = None,
    ip: IpOpt = None,
    title: Annotated[
        str, typer.Option("--title", help="Display title for stream/radio URIs.")
    ] = "",
    radio: Annotated[
        bool, typer.Option("--radio", help="Send radio metadata for stream URLs.")
    ] = False,
) -> None:
    """Open a supported value and start playback."""
    position = _run(
        _with_client(
            room,
            ip,
            lambda c: c.open(value, title=title, radio=radio),
        )
    )
    _print_action(
        f"[green]opened[/] {value}",
        {"status": "opened", "value": value, "position": position or ""},
    )


@app.command()
def track(
    track_id: Annotated[str, typer.Argument(help="Track id, track URI, or track URL.")],
    room: Annotated[
        str | None,
        typer.Option("--room", "-r", help="Target room (falls back to the default speaker)."),
    ] = None,
    ip: IpOpt = None,
    play_next: Annotated[
        bool, typer.Option("--next", help="Enqueue as the next track instead of last.")
    ] = False,
    enqueue_only: Annotated[
        bool,
        typer.Option("--enqueue", help="Only enqueue; do not start playback."),
    ] = False,
) -> None:
    """Play a track by id on a speaker."""
    position = _run(
        _with_client(
            room,
            ip,
            lambda c: c.open_track(track_id, next_=play_next, play=not enqueue_only),
        )
    )
    status = "enqueued" if enqueue_only else "playing"
    _print_action(
        f"[green]{status}[/] {track_id}",
        {"status": status, "track_id": track_id, "position": position or ""},
    )


# --------------------------------------------------------------------------- config


@config_app.command("show")
def config_show() -> None:
    """Show the current local CLI defaults."""
    config = load_config()

    def plain() -> None:
        if not config:
            console.print(f"[dim]no config set[/] ({CONFIG_PATH})")
            return
        for key, value in config.items():
            if isinstance(value, dict):
                console.print(
                    f"{key}: [dim]<{len(value)} entr{'y' if len(value) == 1 else 'ies'}>[/]"
                )
            else:
                console.print(f"{key}: [cyan]{value}[/]")

    _print_object(dict(config), plain)


@config_app.command("set")
def config_set(
    room: Annotated[
        str | None, typer.Option("--room", "-r", help="Set the default room name.")
    ] = None,
    ip: Annotated[str | None, typer.Option("--ip", help="Set the default speaker IP.")] = None,
    output_format: Annotated[
        OutputFormat | None, typer.Option("--format", help="Set the default output format.")
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", help="Set the default SOAP/discovery timeout (seconds)."),
    ] = None,
) -> None:
    """Set persistent CLI defaults so you don't have to pass them every time."""
    if room is None and ip is None and output_format is None and timeout is None:
        raise typer.BadParameter("provide at least one of --room, --ip, --format, --timeout")

    config = load_config()
    if room is not None:
        config["default_room"] = room
        config.pop("default_ip", None)
    if ip is not None:
        config["default_ip"] = ip
        config.pop("default_room", None)
    if output_format is not None:
        config["default_format"] = output_format.value
    if timeout is not None:
        config["default_timeout"] = str(timeout)
    save_config(config)
    _print_action(f"[green]saved[/] config → {config}", {"status": "saved", **config})


@config_app.command("clear")
def config_clear() -> None:
    """Remove all local CLI defaults."""
    CONFIG_PATH.unlink(missing_ok=True)
    _print_action("[green]config cleared[/]", {"status": "cleared"})


if __name__ == "__main__":
    app()
