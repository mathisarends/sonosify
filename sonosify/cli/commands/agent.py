import time

from typer.main import get_command

from sonosify.cli._dependencies import typer
from sonosify.cli.output import print_object, print_records
from sonosify.cli.parameters import IpOpt, RoomArg, RoomOpt, target_room
from sonosify.cli.runtime import async_command, client_for


def register(app: typer.Typer) -> None:
    app.command()(ping)
    app.command()(doctor)
    app.command(name="commands")(commands_command)


@async_command
async def ping(target: RoomArg = None, ip: IpOpt = None, room: RoomOpt = None) -> None:
    """Check whether a speaker responds and report latency."""
    started = time.perf_counter()
    async with client_for(target_room(target, room), ip, coordinator=False) as client:
        room_name = await client.get_room_name()
        address = client.ip
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    data = {
        "reachable": True,
        "room": room_name,
        "ip": address,
        "latency_ms": latency_ms,
    }
    print_object(data, lambda: typer.echo(f"{room_name} {address} {latency_ms} ms"))


@async_command
async def doctor(
    target: RoomArg = None, ip: IpOpt = None, room: RoomOpt = None
) -> None:
    """Run a speaker connectivity and basic service check."""
    started = time.perf_counter()
    async with client_for(target_room(target, room), ip, coordinator=False) as client:
        room_name = await client.get_room_name()
        volume = await client.get_volume()
        address = client.ip
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    data = {
        "healthy": True,
        "room": room_name,
        "ip": address,
        "volume": volume,
        "latency_ms": latency_ms,
    }
    print_object(data, lambda: typer.echo(f"healthy: {room_name} ({address})"))


def commands_command() -> None:
    """Describe all available commands and parameters."""
    from sonosify.cli.app import app

    root = get_command(app)
    records: list[dict[str, object]] = []
    for name, command in sorted(root.commands.items()):
        parameters = []
        for parameter in command.params:
            parameters.append(
                {
                    "name": parameter.name,
                    "kind": parameter.param_type_name,
                    "required": parameter.required,
                    "options": list(getattr(parameter, "opts", ())),
                }
            )
        records.append(
            {
                "name": name,
                "description": (command.help or "").strip(),
                "parameters": parameters,
            }
        )
    print_records(
        records, ["name", "description", "parameters"], lambda: _plain(records)
    )


def _plain(records: list[dict[str, object]]) -> None:
    for record in records:
        typer.echo(f"{record['name']}\t{record['description']}")
