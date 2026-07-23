from typing import Annotated

from sonosify.cli._dependencies import typer

RoomArg = Annotated[
    str | None,
    typer.Argument(
        help="Room name or unique substring; defaults to the configured speaker.",
    ),
]
RoomOpt = Annotated[
    str | None,
    typer.Option(
        "--room",
        "-r",
        help="Target room; defaults to the configured speaker.",
    ),
]
IpOpt = Annotated[
    str | None,
    typer.Option("--ip", help="Target a speaker by IP address instead of room name."),
]
