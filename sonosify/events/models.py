from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from sonosify._parsing import int_or_none
from sonosify.models import Track


class EventService(StrEnum):
    AV_TRANSPORT = "av_transport"
    RENDERING_CONTROL = "rendering_control"


class TransportState(StrEnum):
    STOPPED = "STOPPED"
    PLAYING = "PLAYING"
    TRANSITIONING = "TRANSITIONING"
    PAUSED_PLAYBACK = "PAUSED_PLAYBACK"
    PAUSED_RECORDING = "PAUSED_RECORDING"
    RECORDING = "RECORDING"
    NO_MEDIA_PRESENT = "NO_MEDIA_PRESENT"


DEFAULT_SERVICES = (EventService.AV_TRANSPORT, EventService.RENDERING_CONTROL)

type RawEventValues = dict[str, str]


class BaseSonosEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    service: str
    values: RawEventValues
    sequence: int | None = None
    sid: str = ""


class AVTransportEvent(BaseSonosEvent):
    service: Literal[EventService.AV_TRANSPORT] = EventService.AV_TRANSPORT
    track: Track | None = None
    transport_state: TransportState | None = None


class RenderingControlEvent(BaseSonosEvent):
    service: Literal[EventService.RENDERING_CONTROL] = EventService.RENDERING_CONTROL
    volume: int | None = None
    muted: bool | None = None


class UnknownSonosEvent(BaseSonosEvent):
    pass


type KnownSonosEvent = Annotated[
    AVTransportEvent | RenderingControlEvent,
    Field(discriminator="service"),
]
type SonosEvent = KnownSonosEvent | UnknownSonosEvent

KNOWN_EVENT_ADAPTER = TypeAdapter(KnownSonosEvent)


class AVTransportValues(BaseModel):
    """Typed view of the fields carried by an AVTransport LastChange payload."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    transport_state: TransportState | None = Field(None, alias="TransportState")
    current_track: int | None = Field(None, alias="CurrentTrack")
    current_track_uri: str = Field("", alias="CurrentTrackURI")
    current_track_duration: str = Field("", alias="CurrentTrackDuration")
    current_track_metadata: str = Field("", alias="CurrentTrackMetaData")
    enqueued_metadata: str = Field("", alias="EnqueuedTransportURIMetaData")

    @field_validator("transport_state", mode="before")
    @classmethod
    def _coerce_transport_state(cls, value: object) -> object:
        return _transport_state_or_none(value) if isinstance(value, str) else value

    @field_validator("current_track", mode="before")
    @classmethod
    def _coerce_current_track(cls, value: object) -> object:
        return int_or_none(value) if isinstance(value, str) else value


class RenderingControlValues(BaseModel):
    """Typed view of the fields carried by a RenderingControl LastChange payload."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    volume: int | None = Field(None, alias="Volume")
    muted: bool | None = Field(None, alias="Mute")

    @field_validator("volume", mode="before")
    @classmethod
    def _coerce_volume(cls, value: object) -> object:
        return int_or_none(value) if isinstance(value, str) else value

    @field_validator("muted", mode="before")
    @classmethod
    def _coerce_muted(cls, value: object) -> object:
        return _muted_or_none(value) if isinstance(value, str) else value


def normalize_service(service: str | EventService) -> EventService | None:
    normalized = service.replace("-", "_").casefold()
    if normalized in {"av", "av_transport", "avtransport"}:
        return EventService.AV_TRANSPORT
    if normalized in {"rendering", "rendering_control", "renderingcontrol"}:
        return EventService.RENDERING_CONTROL
    return None


def _muted_or_none(value: str | None) -> bool | None:
    if value == "1":
        return True
    if value == "0":
        return False
    return None


def _transport_state_or_none(value: str | None) -> TransportState | None:
    if value is None:
        return None
    try:
        return TransportState(value)
    except ValueError:
        return None
