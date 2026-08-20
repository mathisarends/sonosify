from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


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


class ClipStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DONE = "DONE"
    DISMISSED = "DISMISSED"
    ERROR = "ERROR"
    INTERRUPTED = "INTERRUPTED"


class AudioClip(BaseModel):
    """Typed view of the ``loadAudioClip`` WebSocket command response."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="allow",
        frozen=True,
        populate_by_name=True,
    )

    id: str
    name: str
    app_id: str
    priority: ClipPriority = ClipPriority.LOW
    clip_type: ClipType | None = None
    status: ClipStatus | None = None
    error_code: str = ""
