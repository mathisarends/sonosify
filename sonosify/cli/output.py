import json
from collections.abc import Callable

from sonosify.cli._dependencies import typer
from sonosify.cli.console import console
from sonosify.cli.state import OutputFormat, state


def print_action(message: str, data: dict[str, object]) -> None:
    match state.format:
        case OutputFormat.JSON:
            typer.echo(json.dumps(data))
        case OutputFormat.TSV:
            typer.echo("\t".join(str(value) for value in data.values()))
        case _:
            console.print(message)


def print_object(data: dict[str, object], plain: Callable[[], None]) -> None:
    match state.format:
        case OutputFormat.JSON:
            typer.echo(json.dumps(data))
        case OutputFormat.TSV:
            for key, value in data.items():
                typer.echo(f"{key}\t{value}")
        case _:
            plain()


def print_records(
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
                typer.echo("\t".join(str(record.get(header, "")) for header in headers))
        case _:
            plain()
