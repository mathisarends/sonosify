from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self
from urllib.parse import quote, urlparse

import httpx

from sonosify.cloud.auth import SonosCloudAuth
from sonosify.cloud.errors import (
    CloudAPIError,
    CloudConfigurationError,
    CloudConnectionError,
    CloudTargetError,
)
from sonosify.cloud.models import (
    AudioClip,
    ClipLEDBehavior,
    ClipPriority,
    ClipType,
    CloudPlayer,
    CloudTopology,
    HomeTheaterOptions,
    Household,
    VolumeState,
)
from sonosify.cloud.settings import _CloudSettings

_CONTROL_API_URL = "https://api.ws.sonos.com/control/api/v1"
_APP_ID_ENV = "SONOSIFY_CLOUD_APP_ID"


def _segment(value: str) -> str:
    return quote(value, safe=":")


class SonosCloudClient:
    def __init__(
        self,
        auth: SonosCloudAuth,
        *,
        app_id: str | None = None,
        timeout: float = 15.0,
        base_url: str = _CONTROL_API_URL,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._auth = auth
        self._app_id = app_id or _CloudSettings().app_id
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._base_url = base_url.rstrip("/")

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    async def get_households(
        self, *, connected_only: bool = True
    ) -> tuple[Household, ...]:
        payload = await self._request(
            "GET",
            "/households",
            params={"connectedOnly": str(connected_only).lower()},
        )
        return tuple(Household.model_validate(item) for item in payload["households"])

    async def get_groups(self, household_id: str) -> CloudTopology:
        payload = await self._request(
            "GET", f"/households/{_segment(household_id)}/groups"
        )
        return CloudTopology.model_validate(payload)

    async def get_players(
        self, household_id: str | None = None
    ) -> tuple[CloudPlayer, ...]:
        if household_id is not None:
            return (await self.get_groups(household_id)).players
        households = await self.get_households()
        players: list[CloudPlayer] = []
        for household in households:
            players.extend((await self.get_groups(household.id)).players)
        return tuple(players)

    async def resolve_player(
        self, query: str, *, household_id: str | None = None
    ) -> CloudPlayer:
        players = await self.get_players(household_id)
        normalized = query.casefold()
        exact = [player for player in players if player.name.casefold() == normalized]
        matches = exact or [
            player for player in players if normalized in player.name.casefold()
        ]
        if len(matches) != 1:
            names = ", ".join(player.name for player in matches) or "none"
            raise CloudTargetError(
                f"expected one cloud player matching {query!r}; matches: {names}"
            )
        return matches[0]

    async def resolve_group(
        self, query: str, *, household_id: str | None = None
    ) -> str:
        household_ids = (
            (household_id,)
            if household_id is not None
            else tuple(item.id for item in await self.get_households())
        )
        groups = [
            group
            for current_id in household_ids
            for group in (await self.get_groups(current_id)).groups
        ]
        normalized = query.casefold()
        exact = [group for group in groups if group.name.casefold() == normalized]
        matches = exact or [
            group for group in groups if normalized in group.name.casefold()
        ]
        if len(matches) != 1:
            names = ", ".join(group.name for group in matches) or "none"
            raise CloudTargetError(
                f"expected one cloud group matching {query!r}; matches: {names}"
            )
        return matches[0].id

    async def play_audio_clip(
        self,
        player_id: str,
        stream_url: str | None = None,
        *,
        name: str = "Voice Assistant",
        app_id: str | None = None,
        volume: int | None = None,
        priority: ClipPriority = ClipPriority.LOW,
        clip_type: ClipType | None = None,
        http_authorization: str | None = None,
        led_behavior: ClipLEDBehavior = ClipLEDBehavior.NONE,
    ) -> AudioClip:
        """Schedule playback through the Sonos ``loadAudioClip`` command."""
        effective_app_id = app_id or self._app_id
        if not effective_app_id:
            raise CloudConfigurationError(_APP_ID_ENV)
        if not 1 <= len(name) <= 64:
            raise ValueError("audio clip name must contain 1 to 64 characters")
        if len(effective_app_id) > 127:
            raise ValueError("app_id must contain at most 127 characters")
        if volume is not None and not 0 <= volume <= 100:
            raise ValueError("audio clip volume must be between 0 and 100")
        if stream_url is not None:
            parsed = urlparse(stream_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("stream_url must be an absolute HTTP(S) URL")

        payload: dict[str, Any] = {
            "name": name,
            "appId": effective_app_id,
            "priority": priority.value,
            "clipLEDBehavior": led_behavior.value,
        }
        if stream_url is not None:
            payload["streamUrl"] = stream_url
        if volume is not None:
            payload["volume"] = volume
        if clip_type is not None:
            payload["clipType"] = clip_type.value
        if http_authorization is not None:
            payload["httpAuthorization"] = http_authorization
        result = await self._request(
            "POST",
            f"/players/{_segment(player_id)}/audioClip",
            json=payload,
        )
        return AudioClip.model_validate(result)

    async def cancel_audio_clip(self, player_id: str, clip_id: str) -> None:
        await self._request(
            "DELETE",
            f"/players/{_segment(player_id)}/audioClip/{_segment(clip_id)}",
        )

    async def play(self, group_id: str) -> None:
        await self._group_command(group_id, "play")

    async def pause(self, group_id: str) -> None:
        await self._group_command(group_id, "pause")

    async def next(self, group_id: str) -> None:
        await self._group_command(group_id, "skipToNextTrack")

    async def previous(self, group_id: str) -> None:
        await self._group_command(group_id, "skipToPreviousTrack")

    async def seek(
        self, group_id: str, position_ms: int, *, item_id: str | None = None
    ) -> None:
        if position_ms < 0:
            raise ValueError("position_ms must not be negative")
        payload: dict[str, Any] = {"positionMillis": position_ms}
        if item_id is not None:
            payload["itemId"] = item_id
        await self._request(
            "POST",
            f"/groups/{_segment(group_id)}/playback/seek",
            json=payload,
        )

    async def get_playback(self, group_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/groups/{_segment(group_id)}/playback")

    async def get_playback_metadata(self, group_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/groups/{_segment(group_id)}/playbackMetadata"
        )

    async def get_player_volume(self, player_id: str) -> VolumeState:
        payload = await self._request(
            "GET", f"/players/{_segment(player_id)}/playerVolume"
        )
        return VolumeState.model_validate(payload)

    async def set_player_volume(
        self,
        player_id: str,
        *,
        volume: int | None = None,
        muted: bool | None = None,
    ) -> None:
        await self._set_volume("players", player_id, "playerVolume", volume, muted)

    async def get_group_volume(self, group_id: str) -> VolumeState:
        payload = await self._request(
            "GET", f"/groups/{_segment(group_id)}/groupVolume"
        )
        return VolumeState.model_validate(payload)

    async def set_group_volume(
        self,
        group_id: str,
        *,
        volume: int | None = None,
        muted: bool | None = None,
    ) -> None:
        await self._set_volume("groups", group_id, "groupVolume", volume, muted)

    async def get_home_theater_options(self, player_id: str) -> HomeTheaterOptions:
        payload = await self._request(
            "GET", f"/players/{_segment(player_id)}/homeTheater/options"
        )
        return HomeTheaterOptions.model_validate(payload)

    async def set_home_theater_options(
        self,
        player_id: str,
        *,
        night_mode: bool | None = None,
        enhance_dialog: bool | None = None,
    ) -> None:
        payload = {
            key: value
            for key, value in {
                "nightMode": night_mode,
                "enhanceDialog": enhance_dialog,
            }.items()
            if value is not None
        }
        if not payload:
            raise ValueError("provide night_mode and/or enhance_dialog")
        await self._request(
            "POST",
            f"/players/{_segment(player_id)}/homeTheater/options",
            json=payload,
        )

    async def _group_command(self, group_id: str, command: str) -> None:
        await self._request(
            "POST",
            f"/groups/{_segment(group_id)}/playback/{command}",
            json={},
        )

    async def _set_volume(
        self,
        target: str,
        target_id: str,
        namespace: str,
        volume: int | None,
        muted: bool | None,
    ) -> None:
        if volume is None and muted is None:
            raise ValueError("provide volume and/or muted")
        if volume is not None and not 0 <= volume <= 100:
            raise ValueError("volume must be between 0 and 100")
        payload = {
            key: value
            for key, value in {"volume": volume, "muted": muted}.items()
            if value is not None
        }
        await self._request(
            "POST",
            f"/{target}/{_segment(target_id)}/{namespace}",
            json=payload,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        token = await self._auth.async_get_valid_token()
        for attempt in range(2):
            try:
                response = await self._http.request(
                    method,
                    f"{self._base_url}{path}",
                    json=json,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "User-Agent": "sonosify/0.2",
                    },
                )
            except httpx.RequestError as exc:
                raise CloudConnectionError(
                    f"cannot reach the Sonos Control API: {exc}"
                ) from exc
            if response.status_code != 401 or attempt:
                break
            token = await self._auth.async_get_valid_token(force_refresh=True)
        if response.is_error:
            details: Any
            try:
                details = response.json()
            except ValueError:
                details = response.text
            error_code = (
                str(details.get("errorCode", "")) if isinstance(details, dict) else ""
            )
            raise CloudAPIError(
                response.status_code,
                error_code=error_code,
                details=details,
            )
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise CloudAPIError(
                response.status_code,
                details={"message": "expected a JSON response"},
            ) from exc
        if not isinstance(payload, dict):
            raise CloudAPIError(
                response.status_code,
                details={"message": "expected a JSON object response"},
            )
        return payload
