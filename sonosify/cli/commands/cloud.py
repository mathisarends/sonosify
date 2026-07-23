from __future__ import annotations

import secrets
from typing import Annotated

from sonosify.cli._dependencies import Table, typer
from sonosify.cli.console import console
from sonosify.cli.output import print_action, print_object, print_records
from sonosify.cli.runtime import async_command
from sonosify.cloud.auth import SonosCloudAuth
from sonosify.cloud.client import SonosCloudClient
from sonosify.cloud.errors import CloudConfigurationError
from sonosify.cloud.models import ClipPriority, ClipType
from sonosify.cloud.settings import _CloudSettings

_HOUSEHOLD_ID_ENV = "SONOSIFY_CLOUD_HOUSEHOLD_ID"

app = typer.Typer(
    help="Use the OAuth-based Sonos Control API.",
    no_args_is_help=True,
)


def _household_id(value: str | None) -> str | None:
    return value or _CloudSettings().household_id


async def _group_id(
    client: SonosCloudClient,
    group: str,
    household_id: str | None,
) -> str:
    if group.startswith("RINCON_") and ":" in group:
        return group
    return await client.resolve_group(group, household_id=household_id)


@app.command("auth-url")
@async_command
async def auth_url(
    state_value: Annotated[
        str | None,
        typer.Option("--state", help="OAuth state value; generated when omitted."),
    ] = None,
) -> None:
    """Create the URL used to authorize sonosify with a Sonos account."""
    state_value = state_value or secrets.token_urlsafe(32)
    url = SonosCloudAuth.from_environment().get_authorization_url(state_value)
    print_object(
        {"authorization_url": url, "state": state_value},
        lambda: typer.echo(url),
    )


@app.command()
@async_command
async def login(
    code: Annotated[
        str,
        typer.Argument(help="Authorization code received at the redirect URI."),
    ],
) -> None:
    """Exchange an authorization code and save the OAuth token locally."""
    auth = SonosCloudAuth.from_environment()
    token = await auth.async_exchange_code(code)
    print_action(
        f"[green]authorized[/] Sonos cloud → {auth.token_cache_path}",
        {
            "status": "authorized",
            "token_cache": str(auth.token_cache_path),
            "expires_in": token.expires_in,
        },
    )


@app.command()
def logout() -> None:
    """Delete the locally cached Sonos OAuth token."""
    auth = SonosCloudAuth.from_environment()
    auth.clear_token()
    print_action(
        "[green]cloud token removed[/]",
        {"status": "logged_out", "token_cache": str(auth.token_cache_path)},
    )


@app.command()
@async_command
async def households(
    all_households: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Include households that are currently disconnected.",
        ),
    ] = False,
) -> None:
    """List households available to the authorized Sonos account."""
    async with SonosCloudClient(SonosCloudAuth.from_environment()) as client:
        items = await client.get_households(connected_only=not all_households)
    records = [{"id": item.id} for item in items]
    print_records(
        records,
        ["id"],
        lambda: _table("Sonos cloud households", records, ["id"]),
    )


@app.command()
@async_command
async def groups(
    household_id: Annotated[
        str | None,
        typer.Option(
            "--household",
            "-H",
            help=f"Household ID (or {_HOUSEHOLD_ID_ENV}).",
        ),
    ] = None,
) -> None:
    """List cloud groups in a household."""
    household_id = _household_id(household_id)
    if not household_id:
        raise CloudConfigurationError(_HOUSEHOLD_ID_ENV)
    async with SonosCloudClient(SonosCloudAuth.from_environment()) as client:
        topology = await client.get_groups(household_id)
    records = [
        {
            "id": group.id,
            "name": group.name,
            "coordinator_id": group.coordinator_id,
            "player_ids": list(group.player_ids),
            "playback_state": group.playback_state,
        }
        for group in topology.groups
    ]
    print_records(
        records,
        ["id", "name", "coordinator_id", "player_ids", "playback_state"],
        lambda: _table(
            "Sonos cloud groups",
            records,
            ["name", "playback_state", "player_ids"],
        ),
    )


@app.command()
@async_command
async def players(
    household_id: Annotated[
        str | None,
        typer.Option(
            "--household",
            "-H",
            help=f"Limit results to a household (or {_HOUSEHOLD_ID_ENV}).",
        ),
    ] = None,
) -> None:
    """List players visible through the Sonos Control API."""
    async with SonosCloudClient(SonosCloudAuth.from_environment()) as client:
        items = await client.get_players(_household_id(household_id))
    records = [
        {
            "id": player.id,
            "name": player.name,
            "capabilities": list(player.capabilities),
            "software_version": player.software_version,
        }
        for player in items
    ]
    print_records(
        records,
        ["id", "name", "capabilities", "software_version"],
        lambda: _table(
            "Sonos cloud players",
            records,
            ["name", "id", "capabilities"],
        ),
    )


@app.command()
@async_command
async def clip(
    stream_url: Annotated[
        str,
        typer.Argument(help="Publicly reachable MP3 or WAV URL."),
    ],
    player: Annotated[
        str,
        typer.Option("--player", "-p", help="Player name or immutable player ID."),
    ],
    household_id: Annotated[
        str | None,
        typer.Option(
            "--household",
            "-H",
            help=f"Household used for name lookup (or {_HOUSEHOLD_ID_ENV}).",
        ),
    ] = None,
    name: Annotated[
        str,
        typer.Option("--name", help="User-visible clip name."),
    ] = "Voice Assistant",
    volume: Annotated[
        int | None,
        typer.Option("--volume", "-v", min=0, max=100, help="Clip volume."),
    ] = None,
    priority: Annotated[
        ClipPriority,
        typer.Option("--priority", case_sensitive=False),
    ] = ClipPriority.LOW,
    voice: Annotated[
        bool,
        typer.Option(
            "--voice",
            help="Mark the clip as VOICE_ASSISTANT instead of a generic custom clip.",
        ),
    ] = False,
    http_authorization: Annotated[
        str | None,
        typer.Option(
            "--http-authorization",
            help="Authorization header Sonos sends when fetching the clip.",
        ),
    ] = None,
) -> None:
    """Schedule an audio clip; Sonos ducks and later resumes current playback."""
    household_id = _household_id(household_id)
    async with SonosCloudClient(SonosCloudAuth.from_environment()) as client:
        player_id = (
            player
            if player.startswith("RINCON_")
            else (await client.resolve_player(player, household_id=household_id)).id
        )
        result = await client.load_audio_clip(
            player_id,
            stream_url,
            name=name,
            volume=volume,
            priority=priority,
            clip_type=ClipType.VOICE_ASSISTANT if voice else ClipType.CUSTOM,
            http_authorization=http_authorization,
        )
    data = result.model_dump(mode="json", by_alias=True)
    print_object(
        data,
        lambda: console.print(
            f"[green]audio clip scheduled[/] {result.id} → {player_id}"
        ),
    )


def _playback_command(name: str):
    def decorator(function):  # type: ignore[no-untyped-def]
        return app.command(name)(async_command(function))

    return decorator


@_playback_command("play")
async def play(
    group: Annotated[
        str,
        typer.Option("--group", "-g", help="Group name or ephemeral group ID."),
    ],
    household_id: Annotated[
        str | None,
        typer.Option(
            "--household",
            "-H",
            help=f"Name lookup scope ({_HOUSEHOLD_ID_ENV}).",
        ),
    ] = None,
) -> None:
    """Start cloud playback on a group."""
    await _run_playback("play", group, _household_id(household_id))


@_playback_command("pause")
async def pause(
    group: Annotated[
        str,
        typer.Option("--group", "-g", help="Group name or ephemeral group ID."),
    ],
    household_id: Annotated[
        str | None,
        typer.Option(
            "--household",
            "-H",
            help=f"Name lookup scope ({_HOUSEHOLD_ID_ENV}).",
        ),
    ] = None,
) -> None:
    """Pause cloud playback on a group."""
    await _run_playback("pause", group, _household_id(household_id))


@_playback_command("next")
async def next_track(
    group: Annotated[
        str,
        typer.Option("--group", "-g", help="Group name or ephemeral group ID."),
    ],
    household_id: Annotated[
        str | None,
        typer.Option(
            "--household",
            "-H",
            help=f"Name lookup scope ({_HOUSEHOLD_ID_ENV}).",
        ),
    ] = None,
) -> None:
    """Skip to the next cloud playback item."""
    await _run_playback("next", group, _household_id(household_id))


@_playback_command("previous")
async def previous_track(
    group: Annotated[
        str,
        typer.Option("--group", "-g", help="Group name or ephemeral group ID."),
    ],
    household_id: Annotated[
        str | None,
        typer.Option(
            "--household",
            "-H",
            help=f"Name lookup scope ({_HOUSEHOLD_ID_ENV}).",
        ),
    ] = None,
) -> None:
    """Skip to the previous cloud playback item."""
    await _run_playback("previous", group, _household_id(household_id))


async def _run_playback(action: str, group: str, household_id: str | None) -> None:
    async with SonosCloudClient(SonosCloudAuth.from_environment()) as client:
        group_id = await _group_id(client, group, household_id)
        await getattr(client, action)(group_id)
    print_action(
        f"[green]{action}[/] → {group}",
        {"status": action, "group_id": group_id},
    )


def _table(
    title: str,
    records: list[dict[str, object]],
    columns: list[str],
) -> None:
    table = Table(title=title)
    for column in columns:
        table.add_column(column.replace("_", " ").title())
    for record in records:
        table.add_row(*(str(record.get(column, "")) for column in columns))
    console.print(table)
