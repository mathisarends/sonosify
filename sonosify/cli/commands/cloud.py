from __future__ import annotations

import secrets
import time
from typing import Annotated
from urllib.parse import parse_qs, urlparse

from sonosify.cli._dependencies import Table, escape, typer
from sonosify.cli.console import console
from sonosify.cli.output import print_action, print_object, print_records
from sonosify.cli.runtime import async_command
from sonosify.cli.state import OutputFormat, state
from sonosify.cloud.auth import SonosCloudAuth
from sonosify.cloud.client import SonosCloudClient
from sonosify.cloud.errors import CloudConfigurationError
from sonosify.cloud.models import ClipPriority, ClipType, OAuthToken
from sonosify.cloud.settings import _CloudSettings

_HOUSEHOLD_ID_ENV = "SONOSIFY_CLOUD_HOUSEHOLD_ID"

app = typer.Typer(
    help="Use the OAuth-based Sonos Control API.",
    no_args_is_help=True,
)


def _household_id(value: str | None) -> str | None:
    return value or _CloudSettings().household_id


def _extract_code(value: str) -> str:
    """Accept a bare authorization code or the full redirect URL and return the code."""
    if "://" not in value:
        return value
    code = parse_qs(urlparse(value).query).get("code")
    if not code:
        raise typer.BadParameter(
            "redirect URL has no 'code' query parameter", param_hint="code"
        )
    return code[0]


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


def _describe_expiry(token: OAuthToken) -> str:
    if token.expires_in <= 0:
        return "no expiry recorded"
    remaining = token.obtained_at + token.expires_in - time.time()
    if remaining <= 0:
        return "expired"
    return f"expires in {int(remaining // 60)}m"


async def _authorize(auth: SonosCloudAuth, code: str) -> None:
    token = await auth.async_exchange_code(code)
    print_action(
        f"[green]authorized[/] Sonos cloud → {auth.token_cache_path}",
        {
            "status": "authorized",
            "token_cache": str(auth.token_cache_path),
            "expires_in": token.expires_in,
        },
    )


async def _onboard(auth: SonosCloudAuth) -> None:
    url = auth.get_authorization_url()
    console.print("[bold]Let's connect your Sonos account.[/]")
    console.print("1. Open this URL in your browser and log in:")
    console.print(f"   [link={url}]{escape(url)}[/link]")
    console.print("2. Approve access — you'll land on your redirect page.")
    value = typer.prompt("3. Paste that page's URL (or just its 'code' value)")
    await _authorize(auth, _extract_code(value))


_SESSION_MENU = (
    ("k", "keep", "leave the session as is"),
    ("r", "refresh", "get a new access token"),
    ("x", "remove", "delete the cached token"),
)


async def _manage_existing_session(auth: SonosCloudAuth, token: OAuthToken) -> None:
    console.print(
        f"[green]Already authorized[/] → {auth.token_cache_path} "
        f"({_describe_expiry(token)})"
    )
    console.print("What would you like to do?")
    for letter, label, description in _SESSION_MENU:
        console.print(f"  [bold]{letter}[/] {label:<8} {description}")

    valid = {letter for letter, _, _ in _SESSION_MENU}
    choice = typer.prompt("Choice", default="k").strip().lower()
    while choice not in valid:
        choice = (
            typer.prompt(f"Please enter one of {sorted(valid)}", default="k")
            .strip()
            .lower()
        )

    match choice:
        case "r":
            refreshed = await auth.async_refresh_token(token.refresh_token or None)
            console.print(
                f"[green]refreshed[/] Sonos cloud token ({_describe_expiry(refreshed)})"
            )
        case "x":
            auth.clear_token()
            console.print("[green]removed[/] cached Sonos cloud token")
        case _:
            console.print("[dim]keeping existing session[/]")


@app.command()
@async_command
async def login(
    code: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Authorization code or full redirect URL, to skip straight to "
                "exchanging it. Omit to run the interactive onboarding wizard, "
                "or to manage an already-cached session."
            )
        ),
    ] = None,
) -> None:
    """Authorize sonosify with a Sonos account, or manage the cached token."""
    auth = SonosCloudAuth.from_environment()

    if code is not None:
        await _authorize(auth, _extract_code(code))
        return

    if state.format is not OutputFormat.PLAIN:
        raise typer.BadParameter(
            "pass the authorization code or redirect URL explicitly "
            "(the interactive wizard needs --format plain)"
        )

    token = auth.load_token()
    if token is None:
        await _onboard(auth)
    else:
        await _manage_existing_session(auth, token)


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
        result = await client.play_audio_clip(
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
