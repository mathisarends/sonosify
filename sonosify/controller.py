from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sonosify.client import DEFAULT_TIMEOUT, SonosClient
from sonosify.discovery import DEFAULT_DISCOVERY_TIMEOUT, discover
from sonosify.events import EventService, EventSubscription
from sonosify.events.models import DEFAULT_SERVICES
from sonosify.topology import SonosSystem


class SonosController:
    __slots__ = ("_discovery_timeout", "_include_invisible", "_system", "_timeout")

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
        include_invisible: bool = False,
    ) -> None:
        self._timeout = timeout
        self._discovery_timeout = discovery_timeout
        self._include_invisible = include_invisible
        self._system: SonosSystem | None = None

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
        self._system = await discover(
            timeout=self._timeout,
            discovery_timeout=self._discovery_timeout,
            include_invisible=self._include_invisible,
        )
        return self._system

    async def client(
        self,
        room: str | None = None,
        *,
        ip: str | None = None,
        coordinator: bool = True,
    ) -> SonosClient:
        if ip is not None:
            return SonosClient(ip, timeout=self._timeout)
        system = self._system or await self.discover()
        return system.client(
            room,
            ip=ip,
            coordinator=coordinator,
            include_invisible=self._include_invisible,
        )

    @asynccontextmanager
    async def watch(
        self,
        room: str | None = None,
        *,
        ip: str | None = None,
        coordinator: bool = True,
        services: tuple[str | EventService, ...] = DEFAULT_SERVICES,
        callback_host: str | None = None,
        callback_port: int = 0,
        timeout_seconds: int = 300,
    ) -> AsyncGenerator[EventSubscription]:
        async with (
            await self.client(room, ip=ip, coordinator=coordinator) as client,
            client.watch(
                services=services,
                callback_host=callback_host,
                callback_port=callback_port,
                timeout_seconds=timeout_seconds,
            ) as watcher,
        ):
            yield watcher

    async def play(self, room: str | None = None, *, ip: str | None = None) -> None:
        async with await self.client(room, ip=ip) as client:
            await client.play()

    async def pause(self, room: str | None = None, *, ip: str | None = None) -> None:
        async with await self.client(room, ip=ip) as client:
            await client.pause()

    async def stop(self, room: str | None = None, *, ip: str | None = None) -> None:
        async with await self.client(room, ip=ip) as client:
            await client.stop()

    async def set_volume(
        self, volume: int, room: str | None = None, *, ip: str | None = None
    ) -> None:
        async with await self.client(room, ip=ip, coordinator=False) as client:
            await client.set_volume(volume)
