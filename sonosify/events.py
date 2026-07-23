import asyncio
import contextlib
import socket
import uuid
from collections.abc import AsyncIterator, Sequence
from enum import StrEnum
from typing import Annotated, Literal, Self
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from sonosify._parsing import int_or_none, local_name, parse_headers
from sonosify.didl import parse_track_metadata
from sonosify.models import Track

_AV_TRANSPORT_EVENT_PATH = "/MediaRenderer/AVTransport/Event"
_RENDERING_CONTROL_EVENT_PATH = "/MediaRenderer/RenderingControl/Event"


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

_KNOWN_EVENT_ADAPTER = TypeAdapter(KnownSonosEvent)


class EventSubscription:
    def __init__(
        self,
        ip: str,
        *,
        port: int = 1400,
        services: Sequence[str | EventService] = DEFAULT_SERVICES,
        callback_host: str | None = None,
        callback_port: int = 0,
        timeout_seconds: int = 300,
        request_timeout: float = 15.0,
    ) -> None:
        self.ip = ip
        self.port = port
        self.services = tuple(services)
        self.callback_host = callback_host
        self.callback_port = callback_port
        self.timeout_seconds = timeout_seconds
        self._http = httpx.AsyncClient(timeout=request_timeout)
        self._events: asyncio.Queue[SonosEvent] = asyncio.Queue()
        self._server: asyncio.AbstractServer | None = None
        self._subscriptions: dict[str, str] = {}
        self._callback_paths: dict[str, str] = {}

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    def __aiter__(self) -> AsyncIterator[SonosEvent]:
        return self

    async def __anext__(self) -> SonosEvent:
        return await self.next_event()

    async def start(self) -> None:
        if self._server is not None:
            return

        callback_host = self.callback_host or await asyncio.to_thread(
            _local_ip_for, self.ip
        )
        self._server = await asyncio.start_server(
            self._handle_connection, callback_host, self.callback_port
        )
        socket_info = self._server.sockets[0].getsockname()
        actual_host = socket_info[0]
        actual_port = socket_info[1]

        for service in self.services:
            callback_path = f"/sonosify/{service}/{uuid.uuid4().hex}"
            self._callback_paths[callback_path] = service
            sid = await self._subscribe(
                service, f"http://{actual_host}:{actual_port}{callback_path}"
            )
            self._subscriptions[service] = sid

    async def next_event(self, timeout: float | None = None) -> SonosEvent:
        if timeout is None:
            return await self._events.get()
        return await asyncio.wait_for(self._events.get(), timeout=timeout)

    async def events(
        self, *, timeout: float | None = None
    ) -> AsyncIterator[SonosEvent]:
        while True:
            yield await self.next_event(timeout=timeout)

    async def close(self) -> None:
        for service, sid in list(self._subscriptions.items()):
            with contextlib.suppress(httpx.HTTPError):
                await self._unsubscribe(service, sid)
        self._subscriptions.clear()

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        await self._http.aclose()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            raw_headers = await reader.readuntil(b"\r\n\r\n")
            header_text = raw_headers.decode(errors="ignore")
            request_line, headers = parse_headers(header_text)
            parts = request_line.split()
            method = parts[0] if parts else ""
            path = parts[1] if len(parts) > 1 else ""
            length = int(headers.get("content-length", "0"))
            body = await reader.readexactly(length) if length else b""

            if method.upper() == "NOTIFY":
                event = parse_notify_event(
                    body,
                    service=self._service_for_path(path),
                    sid=headers.get("sid", ""),
                    sequence=int_or_none(headers.get("seq")),
                )
                await self._events.put(event)
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
            else:
                writer.write(
                    b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n"
                )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _subscribe(self, service: str | EventService, callback_url: str) -> str:
        response = await self._http.request(
            "SUBSCRIBE",
            self._event_url(service),
            headers={
                "CALLBACK": f"<{callback_url}>",
                "NT": "upnp:event",
                "TIMEOUT": f"Second-{self.timeout_seconds}",
            },
        )
        response.raise_for_status()
        return response.headers.get("SID", "")

    async def _unsubscribe(self, service: str | EventService, sid: str) -> None:
        response = await self._http.request(
            "UNSUBSCRIBE", self._event_url(service), headers={"SID": sid}
        )
        response.raise_for_status()

    def _event_url(self, service: str | EventService) -> str:
        path = _event_path(service)
        return f"http://{self.ip}:{self.port}{path}"

    def _service_for_path(self, path: str) -> str:
        return self._callback_paths.get(path, "unknown")


class AVTransportValues(BaseModel):
    """Typed view of the fields carried by an AVTransport LastChange payload."""

    model_config = ConfigDict(populate_by_name=True)

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

    model_config = ConfigDict(populate_by_name=True)

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


def parse_notify_event(
    raw: str | bytes, *, service: str, sid: str = "", sequence: int | None = None
) -> SonosEvent:
    values: RawEventValues = {}
    root = ElementTree.fromstring(raw)
    for property_element in root.iter():
        if local_name(property_element.tag) != "property":
            continue
        for child in list(property_element):
            name = local_name(child.tag)
            text = child.text or ""
            if name == "LastChange":
                values.update(parse_last_change(text))
            else:
                values[name] = text

    normalized_service = _normalize_service(service)
    if normalized_service is None:
        return UnknownSonosEvent(
            service=service, values=values, sequence=sequence, sid=sid
        )

    event_data: dict[str, object] = {
        "service": normalized_service,
        "values": values,
        "sequence": sequence,
        "sid": sid,
    }
    if normalized_service == EventService.AV_TRANSPORT:
        av = AVTransportValues.model_validate(values)
        metadata = av.current_track_metadata or av.enqueued_metadata
        event_data.update(
            track=parse_track_metadata(
                metadata,
                uri=av.current_track_uri,
                duration=av.current_track_duration,
                position=av.current_track,
            )
            if metadata
            else None,
            transport_state=av.transport_state,
        )
    else:
        rc = RenderingControlValues.model_validate(values)
        event_data.update(volume=rc.volume, muted=rc.muted)
    return _KNOWN_EVENT_ADAPTER.validate_python(event_data)


def parse_last_change(raw: str) -> RawEventValues:
    if not raw:
        return {}
    root = ElementTree.fromstring(raw)
    values: RawEventValues = {}
    for element in root.iter():
        name = local_name(element.tag)
        if name in {"Event", "InstanceID"}:
            continue
        value = element.attrib.get("val")
        if value is not None:
            values[name] = value
    return values


def _event_path(service: str | EventService) -> str:
    normalized = _normalize_service(service)
    if normalized == EventService.AV_TRANSPORT:
        return _AV_TRANSPORT_EVENT_PATH
    if normalized == EventService.RENDERING_CONTROL:
        return _RENDERING_CONTROL_EVENT_PATH
    raise ValueError(f"unsupported event service: {service!r}")


def _normalize_service(service: str | EventService) -> EventService | None:
    normalized = service.replace("-", "_").casefold()
    if normalized in {"av", "av_transport", "avtransport"}:
        return EventService.AV_TRANSPORT
    if normalized in {"rendering", "rendering_control", "renderingcontrol"}:
        return EventService.RENDERING_CONTROL
    return None


def _local_ip_for(remote_ip: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((remote_ip, 1400))
        return sock.getsockname()[0]


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
