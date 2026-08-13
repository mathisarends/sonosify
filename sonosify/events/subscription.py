import asyncio
import contextlib
import logging
import socket
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Self
from xml.etree import ElementTree

import httpx

from sonosify._parsing import int_or_none, parse_headers
from sonosify.errors import SubscriptionError
from sonosify.events.models import (
    DEFAULT_SERVICES,
    EventService,
    SonosEvent,
    SubscriptionLost,
    SubscriptionRestored,
    event_path,
    require_service,
)
from sonosify.events.parsing import parse_notify_event
from sonosify.events.router import EventHandler, EventRouter

_MIN_RENEW_INTERVAL = 15.0
_RETRY_INTERVAL = 5.0
_MAX_RETRY_INTERVAL = 60.0

_logger = logging.getLogger("sonosify.events")


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
        self._services = tuple(require_service(service) for service in services)
        self._callback_host = callback_host
        self._callback_port = callback_port
        self._timeout_seconds = timeout_seconds
        self._http = httpx.AsyncClient(timeout=request_timeout)
        self._events: asyncio.Queue[SonosEvent] = asyncio.Queue()
        self._router = EventRouter()
        self._server: asyncio.AbstractServer | None = None
        self._renewals: asyncio.Task[None] | None = None
        self._subscriptions: dict[EventService, str] = {}
        self._callback_urls: dict[EventService, str] = {}
        self._callback_paths: dict[str, EventService] = {}
        self._failures: dict[EventService, Exception] = {}

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def port(self) -> int:
        return self._port

    @property
    def services(self) -> tuple[EventService, ...]:
        """Every requested service; see `subscribed_services` for the live ones."""
        return self._services

    @property
    def subscribed_services(self) -> tuple[EventService, ...]:
        return tuple(self._subscriptions)

    @property
    def connected(self) -> bool:
        """False from the first failed renewal until the player answers again."""
        return self._server is not None and not self._failures

    @property
    def failing_services(self) -> tuple[EventService, ...]:
        return tuple(self._failures)

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

    def on[E: SonosEvent](
        self, *events: type[E]
    ) -> Callable[[EventHandler[E]], EventHandler[E]]:
        """Register a handler with `run()`; see `EventRouter.on`."""
        return self._router.on(*events)

    async def run(self) -> None:
        """Subscribe and feed every incoming event to the registered handlers."""
        await self.start()
        async for event in self:
            await self._router.dispatch(event)

    async def start(self) -> None:
        if self._server is not None:
            return

        callback_host = self._callback_host or await asyncio.to_thread(
            _local_ip_for, self._ip
        )
        self._server = await asyncio.start_server(
            self._handle_connection, callback_host, self._callback_port
        )
        host, port, *_ = self._server.sockets[0].getsockname()

        # No player implements every service — a soundbar-only service such as
        # HTControl answers SUBSCRIBE with 503 on a speaker. Skip those instead
        # of failing the whole subscription.
        rejected: httpx.HTTPError | None = None
        for service in self._services:
            callback_path = f"/sonosify/{service}/{uuid.uuid4().hex}"
            self._callback_paths[callback_path] = service
            self._callback_urls[service] = f"http://{host}:{port}{callback_path}"
            try:
                self._subscriptions[service] = await self._subscribe(service)
            except httpx.HTTPError as exc:
                rejected = exc
                del self._callback_paths[callback_path]
                del self._callback_urls[service]

        if not self._subscriptions:
            await self.close()
            raise SubscriptionError(
                f"{self._ip} accepted no event subscription",
                services=self._services,
            ) from rejected

        self._renewals = asyncio.create_task(self._renew_forever())

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
        if self._renewals is not None:
            self._renewals.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._renewals
            self._renewals = None

        for service, sid in list(self._subscriptions.items()):
            with contextlib.suppress(httpx.HTTPError):
                await self._unsubscribe(service, sid)
        self._subscriptions.clear()
        self._failures.clear()

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        await self._http.aclose()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        # A half-open connection or a truncated request must cost one NOTIFY,
        # not the callback server: asyncio drops the failing task either way,
        # but an unhandled error here also loses the acknowledgement.
        try:
            await self._serve_notify(reader, writer)
        except (OSError, EOFError, asyncio.IncompleteReadError) as error:
            _logger.debug("callback connection from %s failed: %r", self._ip, error)
        except asyncio.LimitOverrunError as error:
            _logger.warning("oversized callback request headers: %r", error)
        finally:
            writer.close()
            with contextlib.suppress(OSError, asyncio.IncompleteReadError):
                await writer.wait_closed()

    async def _serve_notify(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        raw_headers = await reader.readuntil(b"\r\n\r\n")
        request_line, headers = parse_headers(raw_headers.decode(errors="ignore"))
        method, path, *_ = (*request_line.split(), "", "")
        length = int_or_none(headers.get("content-length")) or 0
        body = await reader.readexactly(length) if length > 0 else b""

        if method.upper() != "NOTIFY":
            writer.write(
                b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n"
            )
        else:
            # A player that does not get its 200 back re-sends and eventually
            # drops the subscription, so acknowledge even unusable payloads.
            try:
                await self._events.put(
                    parse_notify_event(
                        body,
                        service=self._callback_paths.get(path, "unknown"),
                        sid=headers.get("sid", ""),
                        sequence=int_or_none(headers.get("seq")),
                    )
                )
            except (ElementTree.ParseError, ValueError) as error:
                _logger.warning("unusable NOTIFY on %s: %r", path, error)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()

    async def _renew_forever(self) -> None:
        """UPnP subscriptions lapse after their TIMEOUT; refresh them at half-life.

        Nothing short of cancellation may end this loop: once it stops, the
        player forgets the subscription within one TIMEOUT and the process goes
        silent forever. While a service is failing the loop retries with a
        short backoff instead of waiting for the next half-life.
        """
        interval = max(self._timeout_seconds / 2, _MIN_RENEW_INTERVAL)
        delay = interval
        retry = _RETRY_INTERVAL
        while True:
            await asyncio.sleep(delay)
            if await self._renew_all():
                delay = retry
                retry = min(retry * 2, _MAX_RETRY_INTERVAL)
            else:
                delay = interval
                retry = _RETRY_INTERVAL

    async def _renew_all(self) -> dict[EventService, Exception]:
        failures: dict[EventService, Exception] = {}
        for service, sid in list(self._subscriptions.items()):
            try:
                self._subscriptions[service] = await self._renew(service, sid)
            except Exception as error:  # noqa: BLE001
                failures[service] = error
        self._report_health(failures)
        return failures

    def _report_health(self, failures: dict[EventService, Exception]) -> None:
        """Turn renewal outcomes into events, on transition only."""
        previous, self._failures = self._failures, failures
        if failures and set(failures) != set(previous):
            error = next(iter(failures.values()))
            _logger.warning(
                "%s stopped renewing %s: %r",
                self._ip,
                ", ".join(failures),
                error,
            )
            self._events.put_nowait(
                SubscriptionLost(affected_services=tuple(failures), error=f"{error!r}")
            )
        elif previous and not failures:
            _logger.info("%s renewed %s again", self._ip, ", ".join(previous))
            self._events.put_nowait(
                SubscriptionRestored(affected_services=tuple(previous))
            )

    async def _subscribe(self, service: EventService) -> str:
        return await self._request(
            service,
            CALLBACK=f"<{self._callback_urls[service]}>",
            NT="upnp:event",
            TIMEOUT=f"Second-{self._timeout_seconds}",
        )

    async def _renew(self, service: EventService, sid: str) -> str:
        try:
            return await self._request(
                service, SID=sid, TIMEOUT=f"Second-{self._timeout_seconds}"
            )
        except httpx.HTTPStatusError:
            # 412 once the player has forgotten the SID: start a fresh one.
            return await self._subscribe(service)

    async def _request(self, service: EventService, **headers: str) -> str:
        response = await self._http.request(
            "SUBSCRIBE", self._event_url(service), headers=headers
        )
        response.raise_for_status()
        return response.headers.get("SID", "")

    async def _unsubscribe(self, service: EventService, sid: str) -> None:
        response = await self._http.request(
            "UNSUBSCRIBE", self._event_url(service), headers={"SID": sid}
        )
        response.raise_for_status()

    def _event_url(self, service: EventService) -> str:
        return f"http://{self._ip}:{self._port}{event_path(service)}"


def _local_ip_for(remote_ip: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((remote_ip, 1400))
        return sock.getsockname()[0]
