import asyncio
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
        self._http: httpx2.AsyncClient | None = None
        self._clients: dict[tuple[str, int], SonosClient] = {}
        self._watchers: set[EventSubscription] = set()

    async def __aenter__(self) -> Self:
        async with self._lock:
            if self._http is not None:
                raise RuntimeError("controller context is already open")
            self._http = httpx2.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    async def close(self) -> None:
        async with self._lock:
            http, self._http = self._http, None
            clients, self._clients = self._clients, {}
            watchers, self._watchers = self._watchers, set()
            self._system = None
            async with AsyncExitStack() as cleanup:
                if http is not None:
                    cleanup.push_async_callback(http.aclose)
                for client in clients.values():
                    cleanup.push_async_callback(client.close)
                for watcher in watchers:
                    cleanup.push_async_callback(watcher.close)

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
        async with self._lock:
            self._require_open()
            return await self._discover()

    async def speakers(self) -> tuple[Speaker, ...]:
        async with self._lock:
            self._require_open()
            system = self._system or await self._discover()
            return system.speakers

    async def speaker(
        self,
        room: str | None = None,
        *,
        ip: str | None = None,
        coordinator: bool = True,
    ) -> SonosClient:
        if room is not None and ip is not None:
            raise ValueError("pass either a room name or an IP address")
        async with self._lock:
            http = self._require_open()
            if ip is not None:
                target = Speaker(ip=ip, room_name="")
            else:
                system = self._system or await self._discover()
                target = system.find(room, include_invisible=self._include_invisible)
                if coordinator:
                    target = system.coordinator_for(target)
            key = (target.ip, target.port)
            client = self._clients.get(key)
            if (
                client is not None
                and target.uid
                and client.uid
                and target.uid != client.uid
            ):
                await client.close()
            if client is None or client.is_closed:
                client = SonosClient.from_speaker(
                    target, timeout=self._timeout, http_client=http
                )
                self._clients[key] = client
            return client

    @asynccontextmanager
    async def watch(
        self,
        room: str | None = None,
        *,
        ip: str | None = None,
        coordinator: bool = True,
        services: Sequence[str | EventService] = DEFAULT_SERVICES,
        callback_host: str | None = None,
        callback_port: int = 0,
        timeout_seconds: int = 300,
    ) -> AsyncGenerator[EventSubscription]:
        client = await self.speaker(room, ip=ip, coordinator=coordinator)
        async with self._lock:
            self._require_open()
            watcher = client.watch(
                services=services,
                callback_host=callback_host,
                callback_port=callback_port,
                timeout_seconds=timeout_seconds,
            )
            await watcher.start()
            self._watchers.add(watcher)
        try:
            yield watcher
        finally:
            async with self._lock:
                if watcher in self._watchers:
                    self._watchers.remove(watcher)
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
        client = await self.speaker(room, ip=ip, coordinator=False)
        await client.set_volume(volume)

    def _require_open(self) -> httpx2.AsyncClient:
        if self._http is None:
            raise RuntimeError(
                "open the controller with 'async with SonosController() as sonos'"
            )
        return self._http

    async def _discover(self) -> SonosSystem:
        self._system = await discover(
            timeout=self._timeout,
            discovery_timeout=self._discovery_timeout,
            include_invisible=self._include_invisible,
        )
        return self._system
