import asyncio
import contextlib
import socket
import uuid
from collections.abc import AsyncIterator, Sequence
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, ConfigDict

from sonosify.didl import parse_track_metadata
from sonosify.models import Track

_AV_TRANSPORT_EVENT_PATH = "/MediaRenderer/AVTransport/Event"
_RENDERING_CONTROL_EVENT_PATH = "/MediaRenderer/RenderingControl/Event"

DEFAULT_SERVICES = ("av_transport", "rendering_control")


class SonosEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    service: str
    values: dict[str, str]
    sequence: int | None = None
    sid: str = ""
    track: Track | None = None

    @property
    def transport_state(self) -> str:
        return self.values.get("TransportState", "")

    @property
    def volume(self) -> int | None:
        value = self.values.get("Volume")
        return int(value) if value and value.isdigit() else None

    @property
    def muted(self) -> bool | None:
        value = self.values.get("Mute")
        if value == "1":
            return True
        if value == "0":
            return False
        return None


class EventSubscription:
    def __init__(
        self,
        ip: str,
        *,
        port: int = 1400,
        services: Sequence[str] = DEFAULT_SERVICES,
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

    async def __aenter__(self) -> EventSubscription:
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

        callback_host = self.callback_host or await asyncio.to_thread(_local_ip_for, self.ip)
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

    async def events(self, *, timeout: float | None = None) -> AsyncIterator[SonosEvent]:
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
            request_line, headers = _parse_http_headers(header_text)
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
                    sequence=_int_or_none(headers.get("seq")),
                )
                await self._events.put(event)
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
            else:
                writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _subscribe(self, service: str, callback_url: str) -> str:
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

    async def _unsubscribe(self, service: str, sid: str) -> None:
        response = await self._http.request(
            "UNSUBSCRIBE", self._event_url(service), headers={"SID": sid}
        )
        response.raise_for_status()

    def _event_url(self, service: str) -> str:
        path = _event_path(service)
        return f"http://{self.ip}:{self.port}{path}"

    def _service_for_path(self, path: str) -> str:
        return self._callback_paths.get(path, "unknown")


def parse_notify_event(
    raw: str | bytes, *, service: str, sid: str = "", sequence: int | None = None
) -> SonosEvent:
    values: dict[str, str] = {}
    root = ElementTree.fromstring(raw)
    for property_element in root.iter():
        if _local_name(property_element.tag) != "property":
            continue
        for child in list(property_element):
            name = _local_name(child.tag)
            text = child.text or ""
            if name == "LastChange":
                values.update(parse_last_change(text))
            else:
                values[name] = text

    track = None
    metadata = values.get("CurrentTrackMetaData") or values.get("EnqueuedTransportURIMetaData")
    if metadata:
        track = parse_track_metadata(
            metadata,
            uri=values.get("CurrentTrackURI", ""),
            duration=values.get("CurrentTrackDuration", ""),
            position=_int_or_none(values.get("CurrentTrack")),
        )
    return SonosEvent(service=service, values=values, sequence=sequence, sid=sid, track=track)


def parse_last_change(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    root = ElementTree.fromstring(raw)
    values: dict[str, str] = {}
    for element in root.iter():
        name = _local_name(element.tag)
        if name in {"Event", "InstanceID"}:
            continue
        value = element.attrib.get("val")
        if value is not None:
            values[name] = value
    return values


def _event_path(service: str) -> str:
    normalized = service.replace("-", "_").casefold()
    if normalized in {"av", "av_transport", "avtransport"}:
        return _AV_TRANSPORT_EVENT_PATH
    if normalized in {"rendering", "rendering_control", "renderingcontrol"}:
        return _RENDERING_CONTROL_EVENT_PATH
    raise ValueError(f"unsupported event service: {service!r}")


def _local_ip_for(remote_ip: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((remote_ip, 1400))
        return sock.getsockname()[0]


def _parse_http_headers(raw: str) -> tuple[str, dict[str, str]]:
    lines = raw.splitlines()
    request_line = lines[0] if lines else ""
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().casefold()] = value.strip()
    return request_line, headers


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _int_or_none(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    return int(value)
