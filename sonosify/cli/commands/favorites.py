from typing import Annotated

from sonosify import SonosClient
from sonosify.cli._dependencies import Table, typer
from sonosify.cli.console import console
from sonosify.cli.output import print_action, print_records
from sonosify.cli.parameters import IpOpt, RoomArg
from sonosify.cli.runtime import run, with_client
from sonosify.errors import SonosifyError

app = typer.Typer(help="List and play Sonos favorites.", no_args_is_help=True)


@app.command("list")
def list_favorites(room: RoomArg = None, ip: IpOpt = None) -> None:
    """List the Sonos favorites available to a speaker."""
    favorites = run(with_client(room, ip, lambda client: client.favorites()))
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

    print_records(records, ["index", "title"], plain)


@app.command("play")
def play_favorite(
    name: Annotated[
        str, typer.Argument(help="Favorite title (or a unique substring).")
    ],
    room: RoomArg = None,
    ip: IpOpt = None,
) -> None:
    """Play a favorite by name on a speaker."""

    async def action(client: SonosClient) -> str:
        favorites = await client.favorites()
        needle = name.casefold()
        matches = [
            favorite for favorite in favorites if needle in favorite.title.casefold()
        ]
        if not matches:
            raise SonosifyError(f"no favorite matching {name!r}")
        if len(matches) > 1:
            titles = ", ".join(favorite.title for favorite in matches)
            raise SonosifyError(f"ambiguous favorite {name!r}; matches: {titles}")
        await client.open_favorite(matches[0])
        return matches[0].title

    title = run(with_client(room, ip, action))
    print_action(
        f"[green]playing favorite[/] {title}",
        {"status": "playing", "favorite": title},
    )
