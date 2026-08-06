import asyncio
import contextlib
import socket
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Self

import httpx

from sonosify._parsing import int_or_none, parse_headers

from .models import DEFAULT_SERVICES, EventService, SonosEvent, normalize_service
from .parsing import parse_notify_event

_AV_TRANSPORT_EVENT_PATH = "/MediaRenderer/AVTransport/Event"
_RENDERING_CONTROL_EVENT_PATH = "/MediaRenderer/RenderingControl/Event"


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
        self._ip = ip
        self._port = port
        self._services = tuple(services)
        self._callback_host = callback_host
        self._callback_port = callback_port
        self._timeout_seconds = timeout_seconds
        self._http = httpx.AsyncClient(timeout=request_timeout)
        self._events: asyncio.Queue[SonosEvent] = asyncio.Queue()
        self._server: asyncio.AbstractServer | None = None
        self._subscriptions: dict[str, str] = {}
        self._callback_paths: dict[str, str] = {}

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def port(self) -> int:
        return self._port

    @property
    def services(self) -> tuple[str | EventService, ...]:
        return self._services

    @property
    def callback_host(self) -> str | None:
        return self._callback_host

    @property
    def callback_port(self) -> int:
        return self._callback_port

    @property
    def timeout_seconds(self) -> int:
        return self._timeout_seconds

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

        callback_host = self._callback_host or await asyncio.to_thread(
            _local_ip_for, self._ip
        )
        self._server = await asyncio.start_server(
            self._handle_connection, callback_host, self._callback_port
        )
        socket_info = self._server.sockets[0].getsockname()
        actual_host = socket_info[0]
        actual_port = socket_info[1]

        for service in self._services:
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
                "TIMEOUT": f"Second-{self._timeout_seconds}",
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
        return f"http://{self._ip}:{self._port}{path}"

    def _service_for_path(self, path: str) -> str:
        return self._callback_paths.get(path, "unknown")


def _event_path(service: str | EventService) -> str:
    normalized = normalize_service(service)
    if normalized == EventService.AV_TRANSPORT:
        return _AV_TRANSPORT_EVENT_PATH
    if normalized == EventService.RENDERING_CONTROL:
        return _RENDERING_CONTROL_EVENT_PATH
    raise ValueError(f"unsupported event service: {service!r}")


def _local_ip_for(remote_ip: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((remote_ip, 1400))
        return sock.getsockname()[0]
