import asyncio
import functools
from collections.abc import AsyncGenerator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Self

import httpx2

from .client import DEFAULT_TIMEOUT, SonosClient
from .discovery import _DEFAULT_DISCOVERY_TIMEOUT, discover
from .events import DEFAULT_SERVICES, EventService, EventSubscription
from .models import Speaker
from .topology import SonosSystem


class SonosController:
    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        discovery_timeout: float = _DEFAULT_DISCOVERY_TIMEOUT,
        include_invisible: bool = False,
    ) -> None:
        self._timeout = timeout
        self._discovery_timeout = discovery_timeout
        self._include_invisible = include_invisible
        self._system: SonosSystem | None = None
        self._lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._discovery_task: asyncio.Task[SonosSystem] | None = None
        self._http: httpx2.AsyncClient | None = None
        self._clients: dict[tuple[str, int], SonosClient] = {}
        self._retired_clients: set[SonosClient] = set()
        self._watchers: dict[EventSubscription, asyncio.Task[None]] = {}

    async def __aenter__(self) -> Self:
        async with self._lifecycle_lock, self._lock:
            if self._http is not None:
                raise RuntimeError("controller context is already open")
            self._http = httpx2.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    async def close(self) -> None:
        async with self._lifecycle_lock:
            async with self._lock:
                http, self._http = self._http, None
                clients, self._clients = self._clients, {}
                retired, self._retired_clients = self._retired_clients, set()
                watchers, self._watchers = self._watchers, {}
                discovery, self._discovery_task = self._discovery_task, None
                self._system = None
            async with AsyncExitStack() as cleanup:
                if http is not None:
                    cleanup.push_async_callback(http.aclose)
                for client in (*clients.values(), *retired):
                    cleanup.push_async_callback(client.close)
                for watcher, startup in watchers.items():
                    cleanup.push_async_callback(watcher.close)
                    cleanup.push_async_callback(_cancel_task, startup)
                if discovery is not None:
                    cleanup.push_async_callback(_cancel_task, discovery)

    @property
    def timeout(self) -> float:
        return self._timeout

    @property
    def discovery_timeout(self) -> float:
        return self._discovery_timeout

    @property
    def include_invisible(self) -> bool:
        return self._include_invisible

    @property
    def system(self) -> SonosSystem | None:
        return self._system

    async def discover(self) -> SonosSystem:
        return await self._get_system(refresh=True)

    async def speakers(self) -> tuple[Speaker, ...]:
        system = await self._get_system()
        return system.speakers

    async def speaker(
        self, room: str | None = None, *, ip: str | None = None
    ) -> SonosClient:
        if room is not None and ip is not None:
            raise ValueError("pass either a room name or an IP address")
        http = self._require_open()
        if ip is not None:
            target = Speaker(ip=ip, room_name="")
        else:
            system = await self._get_system()
            target = system.find(room, include_invisible=self._include_invisible)
        return await self._client_for(target, http)

    async def _client_for(
        self, target: Speaker, http: httpx2.AsyncClient
    ) -> SonosClient:
        previous = None
        async with self._lock:
            self._require_session(http)
            key = (target.ip, target.port)
            client = self._clients.get(key)
            if (
                client is not None
                and target.uid
                and client.uid
                and target.uid != client.uid
            ):
                previous, client = client, None
                self._retired_clients.add(previous)
            if client is None or client.is_closed:
                client = SonosClient.from_speaker(
                    target, timeout=self._timeout, http_client=http
                )
                client._transport_resolver = functools.partial(
                    self._transport_for, target, http
                )
                self._clients[key] = client
        if previous is not None:
            await previous.close()
            self._retired_clients.discard(previous)
        return client

    async def _transport_for(
        self, target: Speaker, http: httpx2.AsyncClient
    ) -> SonosClient:
        async with self._lock:
            self._require_session(http)
            if self._system is not None:
                current = next(
                    (
                        speaker
                        for speaker in self._system.speakers
                        if (speaker.ip, speaker.port) == (target.ip, target.port)
                    ),
                    target,
                )
                target = self._system.coordinator_for(current)
        return await self._client_for(target, http)

    @asynccontextmanager
    async def watch(
        self,
        room: str | None = None,
        *,
        ip: str | None = None,
        services: Sequence[str | EventService] = DEFAULT_SERVICES,
        callback_host: str | None = None,
        callback_port: int = 0,
        timeout_seconds: int = 300,
    ) -> AsyncGenerator[EventSubscription]:
        client = await self.speaker(room, ip=ip)
        async with self._lock:
            self._require_session(client._http)
            watcher = client.watch(
                services=services,
                callback_host=callback_host,
                callback_port=callback_port,
                timeout_seconds=timeout_seconds,
            )
            startup = asyncio.create_task(watcher.start())
            self._watchers[watcher] = startup
        try:
            await startup
            yield watcher
        finally:
            async with self._lock:
                owned = self._watchers.pop(watcher, None)
            if owned is not None:
                await _cancel_task(owned)
                await watcher.close()

    async def play(self, room: str | None = None, *, ip: str | None = None) -> None:
        client = await self.speaker(room, ip=ip)
        await client.play()

    async def pause(self, room: str | None = None, *, ip: str | None = None) -> None:
        client = await self.speaker(room, ip=ip)
        await client.pause()

    async def stop(self, room: str | None = None, *, ip: str | None = None) -> None:
        client = await self.speaker(room, ip=ip)
        await client.stop()

    async def set_volume(
        self, volume: int, room: str | None = None, *, ip: str | None = None
    ) -> None:
        client = await self.speaker(room, ip=ip)
        await client.set_volume(volume)

    def _require_open(self) -> httpx2.AsyncClient:
        if self._http is None:
            raise RuntimeError(
                "open the controller with 'async with SonosController() as sonos'"
            )
        return self._http

    def _require_session(self, http: httpx2.AsyncClient) -> None:
        if self._require_open() is not http:
            raise RuntimeError("controller context changed during operation")

    async def _get_system(self, *, refresh: bool = False) -> SonosSystem:
        async with self._lock:
            http = self._require_open()
            if self._system is not None and not refresh:
                return self._system
            task = self._discovery_task
            if task is None or task.done():
                task = asyncio.create_task(self._discover(http))
                task.add_done_callback(self._discovery_finished)
                self._discovery_task = task
        # Cancelling one lookup must not cancel discovery for other callers.
        return await asyncio.shield(task)

    async def _discover(self, http: httpx2.AsyncClient) -> SonosSystem:
        system = await discover(
            timeout=self._timeout,
            discovery_timeout=self._discovery_timeout,
            include_invisible=self._include_invisible,
        )
        async with self._lock:
            self._require_session(http)
            self._system = system
        return system

    def _discovery_finished(self, task: asyncio.Task[SonosSystem]) -> None:
        if self._discovery_task is task:
            self._discovery_task = None
        if not task.cancelled():
            task.exception()


async def _cancel_task(task: asyncio.Task[object]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
