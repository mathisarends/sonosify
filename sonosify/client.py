from typing import Self

import httpx

from sonosify.didl import parse_favorites, parse_track_metadata, radio_metadata
from sonosify.events import DEFAULT_SERVICES, EventService, EventSubscription
from sonosify.models import Favorite, PlaybackState, Speaker, Track
from sonosify.soap import soap_call
from sonosify.spotify import parse_spotify_uri, spotify_metadata

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
        self.ip = ip
        self.port = port
        self.uid = uid
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)

    @classmethod
    def from_speaker(cls, speaker: Speaker, *, timeout: float = DEFAULT_TIMEOUT) -> Self:
        return cls(speaker.ip, port=speaker.port, uid=speaker.uid, timeout=timeout)

    @property
    def base_url(self) -> str:
        return f"http://{self.ip}:{self.port}"

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> SonosClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

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

    async def play_uri(self, uri: str, *, title: str = "", radio: bool = False) -> None:
        metadata = radio_metadata(title or uri, uri) if radio else ""
        await self.__av_transport("SetAVTransportURI", CurrentURI=uri, CurrentURIMetaData=metadata)
        await self.play()

    async def enqueue_uri(self, uri: str, *, metadata: str = "", next_: bool = False) -> int | None:
        result = await self.__av_transport(
            "AddURIToQueue",
            EnqueuedURI=uri,
            EnqueuedURIMetaData=metadata,
            DesiredFirstTrackNumberEnqueued="0",
            EnqueueAsNext="1" if next_ else "0",
        )
        value = result.get("FirstTrackNumberEnqueued")
        return int(value) if value and value.isdigit() else None

    async def open_spotify(self, value: str, *, title: str = "", next_: bool = False) -> int | None:
        item = parse_spotify_uri(value)
        return await self.enqueue_uri(
            item.sonos_uri, metadata=spotify_metadata(item, title), next_=next_
        )

    async def line_in(self, source: Speaker | str | None = None) -> None:
        source_uid = self._source_uid(source)
        await self.play_uri(f"x-rincon-stream:{source_uid}")

    async def tv(self) -> None:
        if not self.uid:
            raise ValueError(
                "tv playback requires a SonosClient created from a discovered Speaker with uid"
            )
        await self.play_uri(f"x-sonos-htastream:{self.uid}:spdif")

    async def get_volume(self) -> int:
        result = await self._rendering("GetVolume", Channel="Master")
        return int(result.get("CurrentVolume", "0"))

    async def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, volume))
        await self._rendering("SetVolume", Channel="Master", DesiredVolume=str(volume))

    async def get_mute(self) -> bool:
        result = await self._rendering("GetMute", Channel="Master")
        return result.get("CurrentMute") == "1"

    async def set_mute(self, muted: bool) -> None:
        await self._rendering("SetMute", Channel="Master", DesiredMute="1" if muted else "0")

    async def toggle_mute(self) -> bool:
        muted = not await self.get_mute()
        await self.set_mute(muted)
        return muted

    async def get_transport_info(self) -> dict[str, str]:
        return await self.__av_transport("GetTransportInfo")

    async def now_playing(self) -> PlaybackState:
        transport = await self.get_transport_info()
        position = await self.__av_transport("GetPositionInfo")
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

    def watch(
        self,
        *,
        services: tuple[str | EventService, ...] = DEFAULT_SERVICES,
        callback_host: str | None = None,
        callback_port: int = 0,
        timeout_seconds: int = 300,
    ) -> EventSubscription:
        return EventSubscription(
            self.ip,
            port=self.port,
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
        return await self._soap(
            "/MediaRenderer/AVTransport/Control",
            _AV_TRANSPORT,
            action,
            {"InstanceID": "0", **args},
        )

    async def _rendering(self, action: str, **args: object) -> dict[str, str]:
        return await self._soap(
            "/MediaRenderer/RenderingControl/Control",
            _RENDERING_CONTROL,
            action,
            {"InstanceID": "0", **args},
        )

    async def __content_directory(self, action: str, **args: object) -> dict[str, str]:
        return await self._soap(
            "/MediaServer/ContentDirectory/Control", _CONTENT_DIRECTORY, action, args
        )

    async def _soap(
        self,
        path: str,
        service_urn: str,
        action: str,
        args: dict[str, object] | None = None,
    ) -> dict[str, str]:
        return await soap_call(self._http, f"{self.base_url}{path}", service_urn, action, args)

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
