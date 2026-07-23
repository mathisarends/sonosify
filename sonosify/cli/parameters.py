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


def target_room(positional: str | None, option: str | None) -> str | None:
    """Resolve the common positional/--room compatibility pair."""
    if positional and option and positional.casefold() != option.casefold():
        raise typer.BadParameter("room was provided both positionally and with --room")
    return option or positional
