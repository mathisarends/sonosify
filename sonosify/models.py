from pydantic import BaseModel, ConfigDict


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
