from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._parsing import _int_or_none


class TransportState(StrEnum):
    STOPPED = "STOPPED"
    PLAYING = "PLAYING"
    TRANSITIONING = "TRANSITIONING"
    PAUSED_PLAYBACK = "PAUSED_PLAYBACK"
    PAUSED_RECORDING = "PAUSED_RECORDING"
    RECORDING = "RECORDING"
    NO_MEDIA_PRESENT = "NO_MEDIA_PRESENT"


class PlayMode(StrEnum):
    NORMAL = "NORMAL"
    REPEAT_ALL = "REPEAT_ALL"
    REPEAT_ONE = "REPEAT_ONE"
    SHUFFLE_NOREPEAT = "SHUFFLE_NOREPEAT"
    SHUFFLE = "SHUFFLE"
    SHUFFLE_REPEAT_ONE = "SHUFFLE_REPEAT_ONE"


class RepeatMode(StrEnum):
    OFF = "off"
    ONE = "one"
    ALL = "all"


class Speaker(BaseModel):
    model_config = ConfigDict(frozen=True)

    ip: str
    room_name: str
    uid: str = ""
    zone_name: str = ""
    coordinator_uid: str = ""
    is_coordinator: bool = False
    invisible: bool = False
    port: int = 1400


class Group(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    coordinator_uid: str
    members: tuple[Speaker, ...] = ()

    @property
    def coordinator(self) -> Speaker | None:
        return next(
            (speaker for speaker in self.members if speaker.is_coordinator), None
        )


class Track(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str = ""
    creator: str = ""
    album: str = ""
    uri: str = ""
    album_art_uri: str = ""
    duration: str = ""
    position: int | None = None


class PlaybackState(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: str
    track: Track | None = None
    relative_time: str = ""
    absolute_time: str = ""
    track_duration: str = ""


class Favorite(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    uri: str
    metadata: str = ""
    album_art_uri: str = ""


class TransportInfo(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    state: TransportState | None = Field(None, alias="CurrentTransportState")
    status: str = Field("", alias="CurrentTransportStatus")
    speed: str = Field("", alias="CurrentSpeed")

    @field_validator("state", mode="before")
    @classmethod
    def _coerce_state(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            return TransportState(value)
        except ValueError:
            return None


class PositionInfo(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    track: int | None = Field(None, alias="Track")
    track_uri: str = Field("", alias="TrackURI")
    track_duration: str = Field("", alias="TrackDuration")
    track_metadata: str = Field("", alias="TrackMetaData")
    relative_time: str = Field("", alias="RelTime")
    absolute_time: str = Field("", alias="AbsTime")

    @field_validator("track", mode="before")
    @classmethod
    def _coerce_track(cls, value: object) -> object:
        return _int_or_none(value) if isinstance(value, str) else value
