from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CloudModel(BaseModel):
    """Base model tolerant of forward-compatible Sonos response fields."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="allow",
        frozen=True,
        populate_by_name=True,
    )


class OAuthToken(CloudModel):
    access_token: str
    refresh_token: str = ""
    token_type: str = "Bearer"
    expires_in: int = 0
    scope: str = ""
    obtained_at: float = Field(default_factory=time.time)

    def is_expired(self, *, leeway: float = 60.0) -> bool:
        if self.expires_in <= 0:
            return False
        return time.time() >= self.obtained_at + self.expires_in - leeway


class Household(CloudModel):
    id: str


class CloudPlayer(CloudModel):
    id: str
    name: str
    icon: str = ""
    capabilities: tuple[str, ...] = ()
    device_ids: tuple[str, ...] = ()
    api_version: str = ""
    min_api_version: str = ""
    software_version: str = ""
    websocket_url: str = Field("", alias="webSocketUrl")


class CloudGroup(CloudModel):
    id: str
    name: str
    coordinator_id: str
    player_ids: tuple[str, ...] = ()
    playback_state: str = ""


class CloudTopology(CloudModel):
    groups: tuple[CloudGroup, ...] = ()
    players: tuple[CloudPlayer, ...] = ()


class ClipPriority(StrEnum):
    LOW = "LOW"
    HIGH = "HIGH"


class ClipType(StrEnum):
    CHIME = "CHIME"
    CUSTOM = "CUSTOM"
    VOICE_ASSISTANT = "VOICE_ASSISTANT"


class ClipLEDBehavior(StrEnum):
    NONE = "NONE"
    WHITE_LED_QUICK_BREATHING = "WHITE_LED_QUICK_BREATHING"


class AudioClip(CloudModel):
    id: str
    name: str
    app_id: str
    priority: ClipPriority = ClipPriority.LOW
    clip_type: ClipType | None = None
    status: str = ""
    error_code: str = ""


class VolumeState(CloudModel):
    volume: int
    muted: bool
    fixed: bool = False


class HomeTheaterOptions(CloudModel):
    night_mode: bool | None = None
    enhance_dialog: bool | None = None
