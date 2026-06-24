"""Synchronous Sonos device client."""

from __future__ import annotations

from types import TracebackType
from typing import Self

import httpx

from .didl import parse_favorites, parse_track_metadata, radio_metadata
from .events import DEFAULT_SERVICES, EventSubscription
from .models import Favorite, PlaybackState, Speaker, Track
from .soap import soap_call
from .spotify import parse_spotify_uri, spotify_metadata

DEFAULT_TIMEOUT = 15.0

AV_TRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"
RENDERING_CONTROL = "urn:schemas-upnp-org:service:RenderingControl:1"
CONTENT_DIRECTORY = "urn:schemas-upnp-org:service:ContentDirectory:1"
DEVICE_PROPERTIES = "urn:schemas-upnp-org:service:DeviceProperties:1"
ZONE_GROUP_TOPOLOGY = "urn:schemas-upnp-org:service:ZoneGroupTopology:1"


class SonosClient:
    """Low-level client for one Sonos device, usually a group coordinator."""

    def __init__(
        self,
        ip: str,
        *,
        port: int = 1400,
        uid: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.ip = ip
        self.port = port
        self.uid = uid
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)

    @classmethod
    def from_speaker(cls, speaker: Speaker, *, timeout: float = DEFAULT_TIMEOUT) -> SonosClient:
        return cls(speaker.ip, port=speaker.port, uid=speaker.uid, timeout=timeout)

    @property
    def base_url(self) -> str:
        return f"http://{self.ip}:{self.port}"

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def play(self) -> None:
        self._av_transport("Play", Speed="1")

    def pause(self) -> None:
        self._av_transport("Pause")

    def stop(self) -> None:
        self._av_transport("Stop")

    def next(self) -> None:
        self._av_transport("Next")

    def previous(self) -> None:
        self._av_transport("Previous")

    def seek_queue(self, position: int) -> None:
        self._av_transport("Seek", Unit="TRACK_NR", Target=str(position))

    def play_uri(self, uri: str, *, title: str = "", radio: bool = False) -> None:
        metadata = radio_metadata(title or uri, uri) if radio else ""
        self._av_transport("SetAVTransportURI", CurrentURI=uri, CurrentURIMetaData=metadata)
        self.play()

    def enqueue_uri(self, uri: str, *, metadata: str = "", next_: bool = False) -> int | None:
        result = self._av_transport(
            "AddURIToQueue",
            EnqueuedURI=uri,
            EnqueuedURIMetaData=metadata,
            DesiredFirstTrackNumberEnqueued="0",
            EnqueueAsNext="1" if next_ else "0",
        )
        value = result.get("FirstTrackNumberEnqueued")
        return int(value) if value and value.isdigit() else None

    def open_spotify(self, value: str, *, title: str = "", next_: bool = False) -> int | None:
        item = parse_spotify_uri(value)
        return self.enqueue_uri(item.sonos_uri, metadata=spotify_metadata(item, title), next_=next_)

    def line_in(self, source: Speaker | str | None = None) -> None:
        source_uid = self._source_uid(source)
        self.play_uri(f"x-rincon-stream:{source_uid}")

    def tv(self) -> None:
        if not self.uid:
            raise ValueError("tv playback requires a SonosClient created from a discovered Speaker with uid")
        self.play_uri(f"x-sonos-htastream:{self.uid}:spdif")

    def get_volume(self) -> int:
        result = self._rendering("GetVolume", Channel="Master")
        return int(result.get("CurrentVolume", "0"))

    def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, volume))
        self._rendering("SetVolume", Channel="Master", DesiredVolume=str(volume))

    def get_mute(self) -> bool:
        result = self._rendering("GetMute", Channel="Master")
        return result.get("CurrentMute") == "1"

    def set_mute(self, muted: bool) -> None:
        self._rendering("SetMute", Channel="Master", DesiredMute="1" if muted else "0")

    def toggle_mute(self) -> bool:
        muted = not self.get_mute()
        self.set_mute(muted)
        return muted

    def get_transport_info(self) -> dict[str, str]:
        return self._av_transport("GetTransportInfo")

    def now_playing(self) -> PlaybackState:
        transport = self.get_transport_info()
        position = self._av_transport("GetPositionInfo")
        track = parse_track_metadata(
            position.get("TrackMetaData", ""),
            uri=position.get("TrackURI", ""),
            duration=position.get("TrackDuration", ""),
            position=_int_or_none(position.get("Track")),
        )
        return PlaybackState(
            state=transport.get("CurrentTransportState", ""),
            track=track,
            relative_time=position.get("RelTime", ""),
            absolute_time=position.get("AbsTime", ""),
            track_duration=position.get("TrackDuration", ""),
        )

    def queue(self, *, start: int = 0, count: int = 100) -> list[Track]:
        result = self._content_directory(
            "Browse",
            ObjectID="Q:0",
            BrowseFlag="BrowseDirectChildren",
            Filter="*",
            StartingIndex=str(start),
            RequestedCount=str(count),
            SortCriteria="",
        )
        tracks = []
        for index, favorite in enumerate(parse_favorites(result.get("Result", "")), start=start + 1):
            tracks.append(Track(title=favorite.title, uri=favorite.uri, album_art_uri=favorite.album_art_uri, position=index))
        return tracks

    def clear_queue(self) -> None:
        self._av_transport("RemoveAllTracksFromQueue")

    def remove_queue_item(self, position: int) -> None:
        self._av_transport("RemoveTrackFromQueue", ObjectID=f"Q:0/{position}")

    def favorites(self) -> list[Favorite]:
        result = self._content_directory(
            "Browse",
            ObjectID="FV:2",
            BrowseFlag="BrowseDirectChildren",
            Filter="*",
            StartingIndex="0",
            RequestedCount="1000",
            SortCriteria="",
        )
        return parse_favorites(result.get("Result", ""))

    def open_favorite(self, favorite: Favorite) -> None:
        self._av_transport("SetAVTransportURI", CurrentURI=favorite.uri, CurrentURIMetaData=favorite.metadata)
        self.play()

    def watch(
        self,
        *,
        services: tuple[str, ...] = DEFAULT_SERVICES,
        callback_host: str | None = None,
        callback_port: int = 0,
        timeout_seconds: int = 300,
    ) -> EventSubscription:
        """Subscribe to live AVTransport and RenderingControl updates."""

        return EventSubscription(
            self.ip,
            port=self.port,
            services=services,
            callback_host=callback_host,
            callback_port=callback_port,
            timeout_seconds=timeout_seconds,
        )

    def get_zone_group_state(self) -> str:
        return self._soap("/ZoneGroupTopology/Control", ZONE_GROUP_TOPOLOGY, "GetZoneGroupState").get("ZoneGroupState", "")

    def get_room_name(self) -> str:
        return self._soap("/DeviceProperties/Control", DEVICE_PROPERTIES, "GetZoneAttributes").get("CurrentZoneName", "")

    def _av_transport(self, action: str, **args: object) -> dict[str, str]:
        return self._soap("/MediaRenderer/AVTransport/Control", AV_TRANSPORT, action, {"InstanceID": "0", **args})

    def _rendering(self, action: str, **args: object) -> dict[str, str]:
        return self._soap("/MediaRenderer/RenderingControl/Control", RENDERING_CONTROL, action, {"InstanceID": "0", **args})

    def _content_directory(self, action: str, **args: object) -> dict[str, str]:
        return self._soap("/MediaServer/ContentDirectory/Control", CONTENT_DIRECTORY, action, args)

    def _soap(self, path: str, service_urn: str, action: str, args: dict[str, object] | None = None) -> dict[str, str]:
        return soap_call(self._http, f"{self.base_url}{path}", service_urn, action, args)

    def _source_uid(self, source: Speaker | str | None) -> str:
        if isinstance(source, Speaker):
            return source.uid
        if isinstance(source, str):
            return source.removeprefix("uuid:")
        if self.uid:
            return self.uid
        raise ValueError("line-in playback requires a source Speaker or RINCON uid")


def _int_or_none(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    return int(value)
