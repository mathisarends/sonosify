from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sonosify.client import DEFAULT_TIMEOUT, SonosClient
from sonosify.discovery import DEFAULT_DISCOVERY_TIMEOUT, discover
from sonosify.events import DEFAULT_SERVICES, EventService, EventSubscription
from sonosify.topology import SonosSystem


class SonosController:
    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
        include_invisible: bool = False,
    ) -> None:
        self.timeout = timeout
        self.discovery_timeout = discovery_timeout
        self.include_invisible = include_invisible
        self.system: SonosSystem | None = None

    async def discover(self) -> SonosSystem:
        self.system = await discover(
            timeout=self.timeout,
            discovery_timeout=self.discovery_timeout,
            include_invisible=self.include_invisible,
        )
        return self.system

    async def client(
        self,
        room: str | None = None,
        *,
        ip: str | None = None,
        coordinator: bool = True,
    ) -> SonosClient:
        system = self.system or await self.discover()
        return system.client(
            room,
            ip=ip,
            coordinator=coordinator,
            include_invisible=self.include_invisible,
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
    ) -> AsyncIterator[EventSubscription]:
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
