from __future__ import annotations

import asyncio
import functools
import math
from collections.abc import AsyncIterable, Awaitable, Callable, Sequence
from contextlib import AsyncExitStack
from typing import Self
from xml.etree import ElementTree

import httpx2

from ._parsing import _local_name
from ._playback import _play_mode, _repeat_from_play_mode
from ._protocol import _ControlNamespace, _duck_options, _UPnPService
from .clip import (
    AudioClip,
    AudioClipStream,
    ClipLEDBehavior,
    ClipPriority,
    ClipType,
    HostedAudioClip,
    streaming_wav_header,
)
from .clip._pcm import _play_pcm
from .clip._validation import _validate_audio_clip_arguments
from .clip.server import AudioClipServer, _local_ip_for
from .clip.websocket import AudioClipWebSocket
from .didl import (
    parse_favorites,
    parse_track_metadata,
    radio_metadata,
    radio_uri,
)
from .errors import LocalAPIError, NetworkError
from .events import (
    DEFAULT_SERVICES,
    EventService,
    EventSubscription,
)
from .models import (
    Favorite,
    PlaybackState,
    PositionInfo,
    RepeatMode,
    Speaker,
    Track,
    TransportInfo,
)
from .soap import soap_call

DEFAULT_TIMEOUT = 15.0


class SonosClient:
    def __init__(
        self,
        ip: str,
        *,
        port: int = 1400,
        uid: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._ip = ip
        self._port = port
        self._uid = uid
        self._transport_resolver: Callable[[], Awaitable[SonosClient]] | None = None
        self._close_lock = asyncio.Lock()
        self._closed = False
        self._owns_client = http_client is None
        self._http = http_client or httpx2.AsyncClient(timeout=timeout)
        self._audio_clip_websocket = AudioClipWebSocket(ip, timeout=timeout)
        self._audio_clip_server: AudioClipServer | None = None

    @classmethod
    def from_speaker(
        cls,
        speaker: Speaker,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx2.AsyncClient | None = None,
    ) -> Self:
        return cls(
            speaker.ip,
            port=speaker.port,
            uid=speaker.uid,
            timeout=timeout,
            http_client=http_client,
        )

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

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            server, self._audio_clip_server = self._audio_clip_server, None
            async with AsyncExitStack() as cleanup:
                if self._owns_client:
                    cleanup.push_async_callback(self._http.aclose)
                if server is not None:
                    cleanup.push_async_callback(asyncio.to_thread, server.close)
                cleanup.push_async_callback(self._audio_clip_websocket.close)

    async def __aenter__(self) -> Self:
        self._ensure_open()
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
                "namespace": _ControlNamespace.AUDIO_CLIP,
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

        await self.prepare_audio()
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
                "namespace": _ControlNamespace.AUDIO_CLIP,
                "command": "cancelAudioClip",
                "playerId": player_id,
            },
            {"id": clip_id},
        )

    async def stream_audio_clip(
        self,
        *,
        content_type: str = "audio/wav",
        prebuffer_bytes: int = 0,
        local_host: str | None = None,
        app_id: str,
        name: str = "sonosify",
        volume: int | None = None,
        priority: ClipPriority = ClipPriority.LOW,
        clip_type: ClipType | None = None,
        led_behavior: ClipLEDBehavior = ClipLEDBehavior.NONE,
    ) -> AudioClipStream:
        if content_type not in {"audio/mpeg", "audio/wav"}:
            raise ValueError("content_type must be 'audio/mpeg' or 'audio/wav'")
        if prebuffer_bytes < 0:
            raise ValueError("prebuffer_bytes must not be negative")
        _validate_audio_clip_arguments(
            stream_url=None,
            app_id=app_id,
            name=name,
            volume=volume,
            http_authorization=None,
        )

        await self.prepare_audio()
        server = self._ensure_audio_clip_server()
        token, streamed = server.add_stream(content_type)
        host = local_host or _local_ip_for(self._ip)
        stream_url = f"http://{host}:{server.port}/{token}"
        load = functools.partial(
            self.play_audio_clip,
            stream_url,
            app_id=app_id,
            name=name,
            volume=volume,
            priority=priority,
            clip_type=clip_type,
            led_behavior=led_behavior,
        )
        return AudioClipStream(
            streamed=streamed,
            server=server,
            token=token,
            websocket=self._audio_clip_websocket,
            load=load,
            cancel=self.cancel_audio_clip,
            prebuffer_bytes=prebuffer_bytes,
        )

    async def prepare_audio(self) -> None:
        async with self._close_lock:
            player_id = await self._get_or_fetch_player_id()
            await self._audio_clip_websocket.subscribe_audio_clips(player_id)
            self._ensure_audio_clip_server()

    async def play_pcm(
        self,
        chunks: AsyncIterable[bytes],
        *,
        sample_rate: int,
        channels: int = 1,
        sample_width: int = 2,
        prebuffer_seconds: float = 0.0,
        timeout: float | None = 60.0,
        local_host: str | None = None,
        app_id: str,
        name: str = "sonosify",
        volume: int | None = None,
        priority: ClipPriority = ClipPriority.LOW,
        clip_type: ClipType | None = None,
        led_behavior: ClipLEDBehavior = ClipLEDBehavior.NONE,
    ) -> AudioClip:
        header = streaming_wav_header(sample_rate, channels, sample_width)
        if not math.isfinite(prebuffer_seconds) or prebuffer_seconds < 0:
            raise ValueError("prebuffer_seconds must be finite and non-negative")
        frame_size = channels * sample_width
        prebuffer_bytes = (
            len(header) + math.ceil(prebuffer_seconds * sample_rate) * frame_size
            if prebuffer_seconds
            else 0
        )
        async with asyncio.timeout(timeout):
            stream = await self.stream_audio_clip(
                prebuffer_bytes=prebuffer_bytes,
                local_host=local_host,
                app_id=app_id,
                name=name,
                volume=volume,
                priority=priority,
                clip_type=clip_type,
                led_behavior=led_behavior,
            )
            return await _play_pcm(stream, chunks, header=header, frame_size=frame_size)

    async def _get_or_fetch_player_id(self) -> str:
        self._ensure_open()
        if self._uid:
            return self._uid
        try:
            response = await self._http.get(
                f"{self.base_url}/xml/device_description.xml"
            )
            response.raise_for_status()
        except httpx2.HTTPError as exc:
            raise NetworkError(
                f"cannot read Sonos device identity from {self._ip}: {exc}"
            ) from exc
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise LocalAPIError("player returned invalid device metadata") from exc
        for element in root.iter():
            if _local_name(element.tag) == "UDN" and element.text:
                self._uid = element.text.strip().removeprefix("uuid:")
                if self._uid:
                    return self._uid
        raise LocalAPIError("player device metadata contains no UDN")

    def _ensure_audio_clip_server(self) -> AudioClipServer:
        self._ensure_open()
        if self._audio_clip_server is None:
            self._audio_clip_server = AudioClipServer()
        return self._audio_clip_server

    async def play(self) -> None:
        await self._av_transport("Play", Speed="1")

    async def pause(self) -> None:
        await self._av_transport("Pause")

    async def stop(self) -> None:
        await self._av_transport("Stop")

    async def next(self) -> None:
        await self._av_transport("Next")

    async def previous(self) -> None:
        await self._av_transport("Previous")

    async def seek_queue(self, position: int) -> None:
        await self._av_transport("Seek", Unit="TRACK_NR", Target=str(position))

    async def seek(self, position: str) -> None:
        """Seek to an ``H:MM:SS`` position within the current track."""
        await self._av_transport("Seek", Unit="REL_TIME", Target=position)

    async def get_play_mode(self) -> str:
        result = await self._av_transport("GetTransportSettings")
        return result.get("PlayMode", "NORMAL")

    async def set_play_mode(self, mode: str) -> None:
        await self._av_transport("SetPlayMode", NewPlayMode=mode.upper())

    async def set_shuffle(self, enabled: bool) -> str:
        current = await self.get_play_mode()
        repeat = _repeat_from_play_mode(current)
        mode = _play_mode(enabled, repeat)
        await self.set_play_mode(mode)
        return mode

    async def set_repeat(self, repeat: RepeatMode | str) -> str:
        repeat = RepeatMode(repeat)
        current = await self.get_play_mode()
        mode = _play_mode(current.startswith("SHUFFLE"), repeat)
        await self.set_play_mode(mode)
        return mode

    async def get_crossfade(self) -> bool:
        result = await self._av_transport("GetCrossfadeMode")
        return result.get("CrossfadeMode") == "1"

    async def set_crossfade(self, enabled: bool) -> None:
        await self._av_transport(
            "SetCrossfadeMode", CrossfadeMode="1" if enabled else "0"
        )

    async def configure_sleep_timer(self, duration: str | None) -> None:
        await self._av_transport(
            "ConfigureSleepTimer", NewSleepTimerDuration=duration or ""
        )

    async def play_uri(self, uri: str, *, title: str = "", radio: bool = False) -> None:
        if radio:
            uri = radio_uri(uri)
        metadata = radio_metadata(title or uri, uri) if radio else ""
        await self._av_transport(
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
        if next_:
            if isinstance(value, Favorite):
                return await self.enqueue_uri(
                    value.uri, metadata=value.metadata, next_=True
                )
            uri = radio_uri(value) if radio else value
            metadata = radio_metadata(title or uri, uri) if radio else ""
            return await self.enqueue_uri(uri, metadata=metadata, next_=True)
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
        result = await self._av_transport(
            "AddURIToQueue",
            EnqueuedURI=uri,
            EnqueuedURIMetaData=metadata,
            DesiredFirstTrackNumberEnqueued="0",
            EnqueueAsNext="1" if next_ else "0",
        )
        value = result.get("FirstTrackNumberEnqueued")
        position = int(value) if value and value.isdigit() else None
        if play and position is not None:
            transport = await self._transport_client()
            player_id = await transport._get_or_fetch_player_id()
            await self._av_transport(
                "SetAVTransportURI",
                CurrentURI=f"x-rincon-queue:{player_id}#0",
                CurrentURIMetaData="",
            )
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
        result = await self._rendering(
            "SetRelativeVolume",
            Channel="Master",
            Adjustment=str(max(-100, min(100, delta))),
        )
        return int(result["NewVolume"])

    async def get_group_volume(self) -> int:
        result = await self._group_rendering("GetGroupVolume")
        return int(result.get("CurrentVolume", "0"))

    async def set_group_volume(self, volume: int) -> None:
        volume = max(0, min(100, volume))
        await self._group_rendering("SetGroupVolume", DesiredVolume=str(volume))

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

    async def duck(self, duration_millis: int | None = None) -> None:
        await self._player_volume("duck", _duck_options(duration_millis))

    async def unduck(self) -> None:
        await self._player_volume("unduck", {})

    async def get_transport_info(self) -> TransportInfo:
        result = await self._av_transport("GetTransportInfo")
        return TransportInfo.model_validate(result)

    async def get_position_info(self) -> PositionInfo:
        result = await self._av_transport("GetPositionInfo")
        return PositionInfo.model_validate(result)

    async def now_playing(self) -> PlaybackState:
        requests = (
            asyncio.create_task(self.get_transport_info()),
            asyncio.create_task(self.get_position_info()),
        )
        try:
            transport, position = await asyncio.gather(*requests)
        except BaseException:
            for request in requests:
                request.cancel()
            await asyncio.gather(*requests, return_exceptions=True)
            raise
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
        result = await self._content_directory(
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
        await self._av_transport("RemoveAllTracksFromQueue")

    async def remove_queue_item(self, position: int) -> None:
        await self._av_transport("RemoveTrackFromQueue", ObjectID=f"Q:0/{position}")

    async def favorites(self) -> list[Favorite]:
        result = await self._content_directory(
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
        await self._av_transport(
            "SetAVTransportURI",
            CurrentURI=favorite.uri,
            CurrentURIMetaData=favorite.metadata,
        )
        await self.play()

    async def join(self, coordinator: Speaker | str) -> None:
        coordinator_uid = self._source_uid(coordinator)
        await self._soap(
            _UPnPService.AV_TRANSPORT,
            "SetAVTransportURI",
            InstanceID="0",
            CurrentURI=f"x-rincon:{coordinator_uid}",
            CurrentURIMetaData="",
        )

    async def unjoin(self) -> None:
        await self._soap(
            _UPnPService.AV_TRANSPORT,
            "BecomeCoordinatorOfStandaloneGroup",
            InstanceID="0",
        )

    def watch(
        self,
        *,
        services: Sequence[str | EventService] = DEFAULT_SERVICES,
        callback_host: str | None = None,
        callback_port: int = 0,
        timeout_seconds: int = 300,
    ) -> EventSubscription:
        self._ensure_open()
        return EventSubscription(
            self._ip,
            port=self._port,
            services=services,
            callback_host=callback_host,
            callback_port=callback_port,
            timeout_seconds=timeout_seconds,
        )

    async def get_zone_group_state(self) -> str:
        result = await self._soap(_UPnPService.ZONE_GROUP_TOPOLOGY, "GetZoneGroupState")
        return result.get("ZoneGroupState", "")

    async def get_room_name(self) -> str:
        result = await self._soap(_UPnPService.DEVICE_PROPERTIES, "GetZoneAttributes")
        return result.get("CurrentZoneName", "")

    async def _transport_client(self) -> SonosClient:
        self._ensure_open()
        if self._transport_resolver is None:
            return self
        return await self._transport_resolver()

    async def _av_transport(self, action: str, **args: object) -> dict[str, str]:
        transport = await self._transport_client()
        return await transport._soap(
            _UPnPService.AV_TRANSPORT, action, InstanceID="0", **args
        )

    async def _player_volume(self, command: str, options: dict[str, object]) -> None:
        player_id = await self._get_or_fetch_player_id()
        await self._audio_clip_websocket.send_command(
            {
                "namespace": _ControlNamespace.PLAYER_VOLUME,
                "command": command,
                "playerId": player_id,
            },
            options,
        )

    async def _rendering(self, action: str, **args: object) -> dict[str, str]:
        return await self._soap(
            _UPnPService.RENDERING_CONTROL, action, InstanceID="0", **args
        )

    async def _group_rendering(self, action: str, **args: object) -> dict[str, str]:
        transport = await self._transport_client()
        return await transport._soap(
            _UPnPService.GROUP_RENDERING_CONTROL, action, InstanceID="0", **args
        )

    async def _content_directory(self, action: str, **args: object) -> dict[str, str]:
        transport = await self._transport_client()
        return await transport._soap(_UPnPService.CONTENT_DIRECTORY, action, **args)

    async def _soap(
        self, service: _UPnPService, action: str, **args: object
    ) -> dict[str, str]:
        self._ensure_open()
        return await soap_call(
            self._http,
            f"{self.base_url}{service.control_path}",
            service.urn,
            action,
            args,
        )

    def _source_uid(self, source: Speaker | str | None) -> str:
        if isinstance(source, Speaker):
            return source.uid
        if isinstance(source, str):
            return source.removeprefix("uuid:")
        if self._uid:
            return self._uid
        raise ValueError("line-in playback requires a source Speaker or RINCON uid")

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("speaker client is closed")
