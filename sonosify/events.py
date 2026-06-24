"""UPnP event subscription support for live Sonos updates."""

from __future__ import annotations

import queue
import socket
import threading
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Self
from xml.etree import ElementTree

import httpx

from .didl import parse_track_metadata
from .models import Track

AV_TRANSPORT_EVENT_PATH = "/MediaRenderer/AVTransport/Event"
RENDERING_CONTROL_EVENT_PATH = "/MediaRenderer/RenderingControl/Event"

DEFAULT_SERVICES = ("av_transport", "rendering_control")


@dataclass(frozen=True, slots=True)
class SonosEvent:
    """A normalized UPnP event emitted by a Sonos speaker."""

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
    """Context manager that subscribes to Sonos UPnP event callbacks."""

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
        self._http = httpx.Client(timeout=request_timeout)
        self._events: queue.Queue[SonosEvent] = queue.Queue()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._subscriptions: dict[str, str] = {}
        self._callback_paths: dict[str, str] = {}

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __iter__(self) -> Iterator[SonosEvent]:
        while True:
            yield self.next_event()

    def start(self) -> None:
        if self._server is not None:
            return

        callback_host = self.callback_host or _local_ip_for(self.ip)
        subscription = self

        class Handler(BaseHTTPRequestHandler):
            def do_NOTIFY(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                event = parse_notify_event(
                    raw,
                    service=subscription._service_for_path(self.path),
                    sid=self.headers.get("SID", ""),
                    sequence=_int_or_none(self.headers.get("SEQ")),
                )
                subscription._events.put(event)
                self.send_response(200)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer((callback_host, self.callback_port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        actual_host, actual_port = self._server.server_address
        for service in self.services:
            callback_path = f"/sonosify/{service}/{uuid.uuid4().hex}"
            self._callback_paths[callback_path] = service
            sid = self._subscribe(service, f"http://{actual_host}:{actual_port}{callback_path}")
            self._subscriptions[service] = sid

    def next_event(self, timeout: float | None = None) -> SonosEvent:
        """Wait for and return the next live event."""

        return self._events.get(timeout=timeout)

    def events(self, *, timeout: float | None = None) -> Iterator[SonosEvent]:
        """Yield events forever, blocking between updates."""

        while True:
            yield self.next_event(timeout=timeout)

    def close(self) -> None:
        for service, sid in list(self._subscriptions.items()):
            try:
                self._unsubscribe(service, sid)
            except httpx.HTTPError:
                pass
        self._subscriptions.clear()

        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        self._http.close()

    def _subscribe(self, service: str, callback_url: str) -> str:
        response = self._http.request(
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

    def _unsubscribe(self, service: str, sid: str) -> None:
        response = self._http.request("UNSUBSCRIBE", self._event_url(service), headers={"SID": sid})
        response.raise_for_status()

    def _event_url(self, service: str) -> str:
        path = _event_path(service)
        return f"http://{self.ip}:{self.port}{path}"

    def _service_for_path(self, path: str) -> str:
        return self._callback_paths.get(path, "unknown")


def parse_notify_event(raw: str | bytes, *, service: str, sid: str = "", sequence: int | None = None) -> SonosEvent:
    """Parse an incoming UPnP NOTIFY body into a normalized event."""

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
    """Parse Sonos LastChange XML from AVTransport or RenderingControl events."""

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
        return AV_TRANSPORT_EVENT_PATH
    if normalized in {"rendering", "rendering_control", "renderingcontrol"}:
        return RENDERING_CONTROL_EVENT_PATH
    raise ValueError(f"unsupported event service: {service!r}")


def _local_ip_for(remote_ip: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((remote_ip, 1400))
        return sock.getsockname()[0]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _int_or_none(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    return int(value)
