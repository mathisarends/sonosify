from __future__ import annotations

import asyncio
from collections.abc import Sequence
from enum import StrEnum
from typing import Self
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

import sonosify._websocket as _websocket
from sonosify._clip_server import AudioClipServer, _local_ip_for
from sonosify._hosted_clip import HostedAudioClip
from sonosify._parsing import int_or_none, local_name
from sonosify.audio_clip import (
    AudioClip,
    ClipLEDBehavior,
    ClipPriority,
    ClipType,
)
from sonosify.didl import (
    parse_favorites,
    parse_track_metadata,
    radio_metadata,
    radio_uri,
)
from sonosify.errors import LocalAPIError, NetworkError
from sonosify.events import (
    DEFAULT_SERVICES,
    EventService,
    EventSubscription,
    TransportState,
)
from sonosify.models import Favorite, PlaybackState, Speaker, Track
from sonosify.soap import soap_call

DEFAULT_TIMEOUT = 15.0

_AV_TRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"
_RENDERING_CONTROL = "urn:schemas-upnp-org:service:RenderingControl:1"
_CONTENT_DIRECTORY = "urn:schemas-upnp-org:service:ContentDirectory:1"
_DEVICE_PROPERTIES = "urn:schemas-upnp-org:service:DeviceProperties:1"
_ZONE_GROUP_TOPOLOGY = "urn:schemas-upnp-org:service:ZoneGroupTopology:1"


class SonosClient:
    def __init__(
        self,
        ip: str,
        *,
        port: int = 1400,
        uid: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._ip = ip
        self._port = port
        self._uid = uid
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._audio_clip_websocket = _websocket.AudioClipWebSocket(ip, timeout=timeout)
        self._audio_clip_server: AudioClipServer | None = None

    @classmethod
    def from_speaker(
        cls, speaker: Speaker, *, timeout: float = DEFAULT_TIMEOUT
    ) -> Self:
        return cls(speaker.ip, port=speaker.port, uid=speaker.uid, timeout=timeout)

    @property
    def base_url(self) -> str:
        return f"http://{self._ip}:{self._port}"

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def port(self) -> int:
        return self._port

    @property
    def uid(self) -> str:
        return self._uid

    async def close(self) -> None:
        await self._audio_clip_websocket.close()
        if self._audio_clip_server is not None:
            await asyncio.to_thread(self._audio_clip_server.close)
            self._audio_clip_server = None
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    async def play_audio_clip(
        self,
        stream_url: str | None = None,
        *,
        app_id: str,
        name: str = "sonosify",
        volume: int | None = None,
        priority: ClipPriority = ClipPriority.LOW,
        clip_type: ClipType | None = None,
        http_authorization: str | None = None,
        led_behavior: ClipLEDBehavior = ClipLEDBehavior.NONE,
    ) -> AudioClip:
        _validate_audio_clip_arguments(
            stream_url=stream_url,
            app_id=app_id,
            name=name,
            volume=volume,
            http_authorization=http_authorization,
        )

        options: dict[str, object] = {
            "name": name,
            "appId": app_id,
            "priority": priority.value,
            "clipLEDBehavior": led_behavior.value,
        }
        if stream_url is not None:
            options["streamUrl"] = stream_url
        if volume is not None:
            options["volume"] = volume
        if clip_type is not None:
            options["clipType"] = clip_type.value
        if http_authorization is not None:
            options["httpAuthorization"] = http_authorization

        player_id = await self._get_or_fetch_player_id()
        result = await self._audio_clip_websocket.send_command(
            {
                "namespace": "audioClip:1",
                "command": "loadAudioClip",
                "playerId": player_id,
            },
            options,
        )
        return AudioClip.model_validate(result)

    async def play_audio_clip_data(
        self,
        audio: bytes,
        *,
        content_type: str = "audio/wav",
        local_host: str | None = None,
        app_id: str,
        name: str = "sonosify",
        volume: int | None = None,
        priority: ClipPriority = ClipPriority.LOW,
        clip_type: ClipType | None = None,
        led_behavior: ClipLEDBehavior = ClipLEDBehavior.NONE,
    ) -> HostedAudioClip:
        if not audio:
            raise ValueError("audio clip data must not be empty")
        if content_type not in {"audio/mpeg", "audio/wav"}:
            raise ValueError("content_type must be 'audio/mpeg' or 'audio/wav'")
        _validate_audio_clip_arguments(
            stream_url=None,
            app_id=app_id,
            name=name,
            volume=volume,
            http_authorization=None,
        )

        player_id = await self._get_or_fetch_player_id()
        await self._audio_clip_websocket.subscribe_audio_clips(player_id)
        server = self._ensure_audio_clip_server()
        token, fetched = server.add(audio, content_type)
        host = local_host or _local_ip_for(self._ip)
        stream_url = f"http://{host}:{server.port}/{token}"
        try:
            clip = await self.play_audio_clip(
                stream_url,
                app_id=app_id,
                name=name,
                volume=volume,
                priority=priority,
                clip_type=clip_type,
                led_behavior=led_behavior,
            )
        except BaseException:
            server.remove(token)
            raise
        return HostedAudioClip(
            clip,
            fetched=fetched,
            server=server,
            token=token,
            websocket=self._audio_clip_websocket,
            cancel=self.cancel_audio_clip,
        )

    async def cancel_audio_clip(self, clip_id: str) -> None:
        if not clip_id:
            raise ValueError("clip_id must not be empty")
        player_id = await self._get_or_fetch_player_id()
        await self._audio_clip_websocket.send_command(
            {
                "namespace": "audioClip:1",
                "command": "cancelAudioClip",
                "playerId": player_id,
            },
            {"id": clip_id},
        )

    async def _get_or_fetch_player_id(self) -> str:
        if self._uid:
            return self._uid
        try:
            response = await self._http.get(
                f"{self.base_url}/xml/device_description.xml"
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NetworkError(
                f"cannot read Sonos device identity from {self._ip}: {exc}"
            ) from exc
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise LocalAPIError("player returned invalid device metadata") from exc
        for element in root.iter():
            if local_name(element.tag) == "UDN" and element.text:
                self._uid = element.text.strip().removeprefix("uuid:")
                if self._uid:
                    return self._uid
        raise LocalAPIError("player device metadata contains no UDN")

    def _ensure_audio_clip_server(self) -> AudioClipServer:
        if self._audio_clip_server is None:
            self._audio_clip_server = AudioClipServer()
        return self._audio_clip_server

    async def play(self) -> None:
        await self.__av_transport("Play", Speed="1")

    async def pause(self) -> None:
        await self.__av_transport("Pause")

    async def stop(self) -> None:
        await self.__av_transport("Stop")

    async def next(self) -> None:
        await self.__av_transport("Next")

    async def previous(self) -> None:
        await self.__av_transport("Previous")

    async def seek_queue(self, position: int) -> None:
        await self.__av_transport("Seek", Unit="TRACK_NR", Target=str(position))

    async def seek(self, position: str) -> None:
        """Seek to an ``H:MM:SS`` position within the current track."""
        await self.__av_transport("Seek", Unit="REL_TIME", Target=position)

    async def get_play_mode(self) -> str:
        result = await self.__av_transport("GetTransportSettings")
        return result.get("PlayMode", "NORMAL")

    async def set_play_mode(self, mode: str) -> None:
        await self.__av_transport("SetPlayMode", NewPlayMode=mode.upper())

    async def set_shuffle(self, enabled: bool) -> str:
        current = await self.get_play_mode()
        repeat = _repeat_from_play_mode(current)
        mode = _play_mode(enabled, repeat)
        await self.set_play_mode(mode)
        return mode

    async def set_repeat(self, repeat: _RepeatMode | str) -> str:
        repeat = _RepeatMode(repeat)
        current = await self.get_play_mode()
        mode = _play_mode(current.startswith("SHUFFLE"), repeat)
        await self.set_play_mode(mode)
        return mode

    async def get_crossfade(self) -> bool:
        result = await self.__av_transport("GetCrossfadeMode")
        return result.get("CrossfadeMode") == "1"

    async def set_crossfade(self, enabled: bool) -> None:
        await self.__av_transport(
            "SetCrossfadeMode", CrossfadeMode="1" if enabled else "0"
        )

    async def configure_sleep_timer(self, duration: str | None) -> None:
        await self.__av_transport(
            "ConfigureSleepTimer", NewSleepTimerDuration=duration or ""
        )

    async def play_uri(self, uri: str, *, title: str = "", radio: bool = False) -> None:
        if radio:
            uri = radio_uri(uri)
        metadata = radio_metadata(title or uri, uri) if radio else ""
        await self.__av_transport(
            "SetAVTransportURI", CurrentURI=uri, CurrentURIMetaData=metadata
        )
        await self.play()

    async def open(
        self,
        value: str | Favorite,
        *,
        title: str = "",
        radio: bool = False,
        next_: bool = False,
    ) -> int | None:
        if isinstance(value, Favorite):
            await self.open_favorite(value)
            return None
        await self.play_uri(value, title=title, radio=radio)
        return None

    async def enqueue_uri(
        self,
        uri: str,
        *,
        metadata: str = "",
        next_: bool = False,
        play: bool = False,
    ) -> int | None:
        result = await self.__av_transport(
            "AddURIToQueue",
            EnqueuedURI=uri,
            EnqueuedURIMetaData=metadata,
            DesiredFirstTrackNumberEnqueued="0",
            EnqueueAsNext="1" if next_ else "0",
        )
        value = result.get("FirstTrackNumberEnqueued")
        position = int(value) if value and value.isdigit() else None
        if play and position is not None:
            await self.seek_queue(position)
            await self.play()
        return position

    async def line_in(self, source: Speaker | str | None = None) -> None:
        source_uid = self._source_uid(source)
        await self.play_uri(f"x-rincon-stream:{source_uid}")

    async def tv(self) -> None:
        if not self._uid:
            raise ValueError(
                "tv playback requires a SonosClient created from a "
                "discovered Speaker with uid"
            )
        await self.play_uri(f"x-sonos-htastream:{self._uid}:spdif")

    async def get_volume(self) -> int:
        result = await self._rendering("GetVolume", Channel="Master")
        return int(result.get("CurrentVolume", "0"))

    async def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, volume))
        await self._rendering("SetVolume", Channel="Master", DesiredVolume=str(volume))

    async def adjust_volume(self, delta: int) -> int:
        volume = max(0, min(100, await self.get_volume() + delta))
        await self.set_volume(volume)
        return volume

    async def get_group_volume(self) -> int:
        result = await self._rendering("GetGroupVolume")
        return int(result.get("CurrentVolume", "0"))

    async def set_group_volume(self, volume: int) -> None:
        volume = max(0, min(100, volume))
        await self._rendering("SetGroupVolume", DesiredVolume=str(volume))

    async def adjust_group_volume(self, delta: int) -> int:
        volume = max(0, min(100, await self.get_group_volume() + delta))
        await self.set_group_volume(volume)
        return volume

    async def get_mute(self) -> bool:
        result = await self._rendering("GetMute", Channel="Master")
        return result.get("CurrentMute") == "1"

    async def set_mute(self, muted: bool) -> None:
        await self._rendering(
            "SetMute", Channel="Master", DesiredMute="1" if muted else "0"
        )

    async def toggle_mute(self) -> bool:
        muted = not await self.get_mute()
        await self.set_mute(muted)
        return muted

    async def get_transport_info(self) -> TransportInfo:
        result = await self.__av_transport("GetTransportInfo")
        return TransportInfo.model_validate(result)

    async def get_position_info(self) -> PositionInfo:
        result = await self.__av_transport("GetPositionInfo")
        return PositionInfo.model_validate(result)

    async def now_playing(self) -> PlaybackState:
        transport = await self.get_transport_info()
        position = await self.get_position_info()
        track = parse_track_metadata(
            position.track_metadata,
            uri=position.track_uri,
            duration=position.track_duration,
            position=position.track,
        )
        return PlaybackState(
            state=transport.state.value if transport.state else "",
            track=track,
            relative_time=position.relative_time,
            absolute_time=position.absolute_time,
            track_duration=position.track_duration,
        )

    async def queue(self, *, start: int = 0, count: int = 100) -> list[Track]:
        result = await self.__content_directory(
            "Browse",
            ObjectID="Q:0",
            BrowseFlag="BrowseDirectChildren",
            Filter="*",
            StartingIndex=str(start),
            RequestedCount=str(count),
            SortCriteria="",
        )
        tracks = []
        for index, favorite in enumerate(
            parse_favorites(result.get("Result", "")), start=start + 1
        ):
            tracks.append(
                Track(
                    title=favorite.title,
                    uri=favorite.uri,
                    album_art_uri=favorite.album_art_uri,
                    position=index,
                )
            )
        return tracks

    async def clear_queue(self) -> None:
        await self.__av_transport("RemoveAllTracksFromQueue")

    async def remove_queue_item(self, position: int) -> None:
        await self.__av_transport("RemoveTrackFromQueue", ObjectID=f"Q:0/{position}")

    async def favorites(self) -> list[Favorite]:
        result = await self.__content_directory(
            "Browse",
            ObjectID="FV:2",
            BrowseFlag="BrowseDirectChildren",
            Filter="*",
            StartingIndex="0",
            RequestedCount="1000",
            SortCriteria="",
        )
        return parse_favorites(result.get("Result", ""))

    async def open_favorite(self, favorite: Favorite) -> None:
        await self.__av_transport(
            "SetAVTransportURI",
            CurrentURI=favorite.uri,
            CurrentURIMetaData=favorite.metadata,
        )
        await self.play()

    async def join(self, coordinator: Speaker | str) -> None:
        coordinator_uid = self._source_uid(coordinator)
        await self.__av_transport(
            "SetAVTransportURI",
            CurrentURI=f"x-rincon:{coordinator_uid}",
            CurrentURIMetaData="",
        )

    async def unjoin(self) -> None:
        await self.__av_transport("BecomeCoordinatorOfStandaloneGroup")

    def watch(
        self,
        *,
        services: Sequence[str | EventService] = DEFAULT_SERVICES,
        callback_host: str | None = None,
        callback_port: int = 0,
        timeout_seconds: int = 300,
    ) -> EventSubscription:
        return EventSubscription(
            self._ip,
            port=self._port,
            services=services,
            callback_host=callback_host,
            callback_port=callback_port,
            timeout_seconds=timeout_seconds,
        )

    async def get_zone_group_state(self) -> str:
        result = await self._soap(
            "/ZoneGroupTopology/Control", _ZONE_GROUP_TOPOLOGY, "GetZoneGroupState"
        )
        return result.get("ZoneGroupState", "")

    async def get_room_name(self) -> str:
        result = await self._soap(
            "/DeviceProperties/Control", _DEVICE_PROPERTIES, "GetZoneAttributes"
        )
        return result.get("CurrentZoneName", "")

    async def __av_transport(self, action: str, **args: object) -> dict[str, str]:
        kwargs = {
            "InstanceID": "0",
            **args,
        }
        return await self._soap(
            path="/MediaRenderer/AVTransport/Control",
            service_urn=_AV_TRANSPORT,
            action=action,
            **kwargs,
        )

    async def _rendering(self, action: str, **args: object) -> dict[str, str]:
        kwargs = {
            "InstanceID": "0",
            **args,
        }
        return await self._soap(
            path="/MediaRenderer/RenderingControl/Control",
            service_urn=_RENDERING_CONTROL,
            action=action,
            **kwargs,
        )

    async def __content_directory(self, action: str, **args: object) -> dict[str, str]:
        kwargs = {**args}
        return await self._soap(
            path="/MediaServer/ContentDirectory/Control",
            service_urn=_CONTENT_DIRECTORY,
            action=action,
            **kwargs,
        )

    async def _soap(
        self,
        path: str,
        service_urn: str,
        action: str,
        **args: object,
    ) -> dict[str, str]:
        return await soap_call(
            self._http, f"{self.base_url}{path}", service_urn, action, args
        )

    def _source_uid(self, source: Speaker | str | None) -> str:
        if isinstance(source, Speaker):
            return source.uid
        if isinstance(source, str):
            return source.removeprefix("uuid:")
        if self._uid:
            return self._uid
        raise ValueError("line-in playback requires a source Speaker or RINCON uid")


class TransportInfo(BaseModel):
    """Typed view of the AVTransport GetTransportInfo response."""

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
    """Typed view of the AVTransport GetPositionInfo response."""

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
        return int_or_none(value) if isinstance(value, str) else value


class _RepeatMode(StrEnum):
    OFF = "off"
    ONE = "one"
    ALL = "all"


def _validate_audio_clip_arguments(
    *,
    stream_url: str | None,
    app_id: str,
    name: str,
    volume: int | None,
    http_authorization: str | None,
) -> None:
    if not 1 <= len(name) <= 64:
        raise ValueError("audio clip name must contain 1 to 64 characters")
    if not app_id or len(app_id) > 127:
        raise ValueError("app_id must contain 1 to 127 characters")
    if volume is not None and not 0 <= volume <= 100:
        raise ValueError("audio clip volume must be between 0 and 100")
    if stream_url is not None:
        parsed = urlparse(stream_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("stream_url must be an absolute HTTP(S) URL")
    if http_authorization is not None and len(http_authorization.encode()) > 512:
        raise ValueError("http_authorization must contain at most 512 bytes")


def _repeat_from_play_mode(mode: str) -> _RepeatMode:
    if mode.endswith("REPEAT_ONE"):
        return _RepeatMode.ONE
    if mode in {"REPEAT_ALL", "SHUFFLE"}:
        return _RepeatMode.ALL
    return _RepeatMode.OFF


def _play_mode(shuffle: bool, repeat: _RepeatMode) -> str:
    if shuffle:
        return {
            _RepeatMode.OFF: "SHUFFLE_NOREPEAT",
            _RepeatMode.ONE: "SHUFFLE_REPEAT_ONE",
            _RepeatMode.ALL: "SHUFFLE",
        }[repeat]
    return {
        _RepeatMode.OFF: "NORMAL",
        _RepeatMode.ONE: "REPEAT_ONE",
        _RepeatMode.ALL: "REPEAT_ALL",
    }[repeat]
