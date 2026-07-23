import asyncio
from typing import Annotated

from sonosify import SonosClient, SonosController
from sonosify.cli._dependencies import Table, typer
from sonosify.cli.console import console
from sonosify.cli.output import print_action, print_records
from sonosify.cli.parameters import IpOpt, RoomArg
from sonosify.cli.runtime import async_command, client_for
from sonosify.cli.state import state


def register(app: typer.Typer) -> None:
    app.command()(groups)
    app.command()(group)
    app.command()(ungroup)


@async_command
async def groups() -> None:
    """List the current Sonos groups and their members."""
    system = await SonosController(timeout=state.timeout).discover()
    records = [
        {
            "id": group.id,
            "coordinator": group.coordinator.room_name if group.coordinator else "",
            "coordinator_uid": group.coordinator_uid,
            "members": [speaker.room_name for speaker in group.members],
        }
        for group in system.groups
    ]

    def plain() -> None:
        table = Table(title="Sonos groups")
        table.add_column("Coordinator", style="cyan")
        table.add_column("Members")
        for record in records:
            table.add_row(
                str(record["coordinator"]),
                ", ".join(record["members"]),
            )
        console.print(table)

    print_records(records, ["id", "coordinator", "coordinator_uid", "members"], plain)


@async_command
async def group(
    coordinator: Annotated[str, typer.Argument(help="Coordinator room name.")],
    members: Annotated[
        list[str] | None,
        typer.Option("--with", help="Room to join; repeat for multiple rooms."),
    ] = None,
) -> None:
    """Join one or more rooms to a coordinator."""
    if not members:
        raise typer.BadParameter("provide at least one --with room")
    system = await SonosController(timeout=state.timeout).discover()
    coordinator_speaker = system.find(coordinator)

    async def join(room: str) -> str:
        speaker = system.find(room)
        async with SonosClient.from_speaker(speaker, timeout=state.timeout) as client:
            await client.join(coordinator_speaker)
        return speaker.room_name

    joined = await asyncio.gather(*(join(room) for room in members))
    print_action(
        f"[green]grouped[/] {', '.join(joined)} with {coordinator_speaker.room_name}",
        {"coordinator": coordinator_speaker.room_name, "members": joined},
    )


@async_command
async def ungroup(room: RoomArg = None, ip: IpOpt = None) -> None:
    """Remove a room from its current group."""
    async with client_for(room, ip, coordinator=False) as client:
        await client.unjoin()
    print_action("[green]ungrouped[/]", {"status": "ungrouped"})
