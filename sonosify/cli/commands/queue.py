from typing import Annotated

from sonosify.cli._dependencies import Table, typer
from sonosify.cli.console import console
from sonosify.cli.output import print_action, print_records
from sonosify.cli.parameters import IpOpt, RoomArg
from sonosify.cli.runtime import async_command, client_for


def register(app: typer.Typer) -> None:
    app.command()(queue)
    app.command()(enqueue)


@async_command
async def queue(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Show the playback queue of a speaker."""
    async with client_for(room, ip) as client:
        tracks = await client.queue()
    records: list[dict[str, object]] = [
        {"position": track.position or "", "title": track.title or track.uri}
        for track in tracks
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

    print_records(records, ["position", "title"], plain)


@async_command
async def enqueue(
    uri: Annotated[str, typer.Argument(help="URI to add to the Sonos queue.")],
    room: Annotated[
        str | None,
        typer.Option(
            "--room", "-r", help="Target room (falls back to the default speaker)."
        ),
    ] = None,
    ip: IpOpt = None,
    play_next: Annotated[
        bool,
        typer.Option(
            "--next/--queue", help="Enqueue as the next track instead of last."
        ),
    ] = False,
    play_now: Annotated[
        bool,
        typer.Option("--play", help="Start playback at the enqueued queue position."),
    ] = False,
) -> None:
    """Add a URI to the speaker queue."""
    async with client_for(room, ip) as client:
        position = await client.enqueue_uri(
            uri,
            next_=play_next,
            play=play_now,
        )
    status = "playing" if play_now else "enqueued"
    print_action(
        f"[green]{status}[/] {uri}",
        {"status": status, "uri": uri, "position": position or ""},
    )
