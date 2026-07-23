from typing import Annotated

from sonosify.cli._dependencies import Table, typer
from sonosify.cli.console import console
from sonosify.cli.output import print_action, print_records
from sonosify.cli.parameters import IpOpt, RoomArg, RoomOpt
from sonosify.cli.runtime import async_command, client_for

app = typer.Typer(
    help="Inspect and manage a speaker queue.",
    invoke_without_command=True,
)


def register(root: typer.Typer) -> None:
    root.add_typer(app, name="queue")
    root.command()(enqueue)


@app.callback()
@async_command
async def queue(
    ctx: typer.Context,
    room: RoomOpt = None,
    ip: IpOpt = None,
) -> None:
    """Show the playback queue of a speaker."""
    if ctx.invoked_subcommand is not None:
        return
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


@app.command("clear")
@async_command
async def clear_queue(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Remove every item from the queue."""
    async with client_for(room, ip) as client:
        await client.clear_queue()
    print_action("[green]queue cleared[/]", {"status": "cleared"})


@app.command("remove")
@async_command
async def remove_queue_item(
    position: Annotated[int, typer.Argument(min=1, help="Queue position to remove.")],
    room: RoomArg = None,
    ip: IpOpt = None,
) -> None:
    """Remove one queue item by its one-based position."""
    async with client_for(room, ip) as client:
        await client.remove_queue_item(position)
    print_action("[green]queue item removed[/]", {"position": position})


@app.command("jump")
@async_command
async def jump_queue(
    position: Annotated[int, typer.Argument(min=1, help="Queue position to play.")],
    room: RoomArg = None,
    ip: IpOpt = None,
) -> None:
    """Jump to and play one queue item."""
    async with client_for(room, ip) as client:
        await client.seek_queue(position)
        await client.play()
    print_action("[green]queue position playing[/]", {"position": position})


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
