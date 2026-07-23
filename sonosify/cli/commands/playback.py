from typing import Annotated

from sonosify.cli._dependencies import typer
from sonosify.cli.output import print_action
from sonosify.cli.parameters import IpOpt, RoomArg
from sonosify.cli.runtime import run, with_client


def register(app: typer.Typer) -> None:
    app.command()(play)
    app.command()(pause)
    app.command()(stop)
    app.command()(next)
    app.command()(previous)


def play(
    target: Annotated[
        str | None,
        typer.Argument(help="Room name. Falls back to the configured default speaker."),
    ] = None,
    ip: IpOpt = None,
) -> None:
    """Resume playback on a speaker."""
    run(with_client(target, ip, lambda client: client.play()))
    print_action("[green]playing[/]", {"status": "playing"})


def pause(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Pause playback on a speaker."""
    run(with_client(room, ip, lambda client: client.pause()))
    print_action("[yellow]paused[/]", {"status": "paused"})


def stop(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Stop playback on a speaker."""
    run(with_client(room, ip, lambda client: client.stop()))
    print_action("[yellow]stopped[/]", {"status": "stopped"})


def next(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Skip to the next track."""
    run(with_client(room, ip, lambda client: client.next()))
    print_action("[green]next[/]", {"status": "next"})


def previous(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Skip to the previous track."""
    run(with_client(room, ip, lambda client: client.previous()))
    print_action("[green]previous[/]", {"status": "previous"})
