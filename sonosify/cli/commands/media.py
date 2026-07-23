from typing import Annotated

from sonosify.cli._dependencies import typer
from sonosify.cli.output import print_action
from sonosify.cli.parameters import IpOpt
from sonosify.cli.runtime import run, with_client


def register(app: typer.Typer) -> None:
    app.command()(open)
    app.command()(track)


def open(
    value: Annotated[str, typer.Argument(help="Stream URL or playable Sonos URI.")],
    room: Annotated[
        str | None,
        typer.Option(
            "--room", "-r", help="Target room (falls back to the default speaker)."
        ),
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
    position = run(
        with_client(
            room,
            ip,
            lambda client: client.open(value, title=title, radio=radio),
        )
    )
    print_action(
        f"[green]opened[/] {value}",
        {"status": "opened", "value": value, "position": position or ""},
    )


def track(
    track_id: Annotated[str, typer.Argument(help="Track id, track URI, or track URL.")],
    room: Annotated[
        str | None,
        typer.Option(
            "--room", "-r", help="Target room (falls back to the default speaker)."
        ),
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
    position = run(
        with_client(
            room,
            ip,
            lambda client: client.open_track(
                track_id,
                next_=play_next,
                play=not enqueue_only,
            ),
        )
    )
    status = "enqueued" if enqueue_only else "playing"
    print_action(
        f"[green]{status}[/] {track_id}",
        {"status": status, "track_id": track_id, "position": position or ""},
    )
