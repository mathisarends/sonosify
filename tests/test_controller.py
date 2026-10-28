from __future__ import annotations

import asyncio

import httpx2
import pytest

import sonosify.client as client_module
import sonosify.controller as controller_module
from sonosify import SonosController
from sonosify.errors import DiscoveryError
from sonosify.models import Speaker
from sonosify.topology import SonosSystem


@pytest.fixture
def household(monkeypatch: pytest.MonkeyPatch) -> SonosSystem:
    system = SonosSystem(
        (
            Speaker(ip="192.168.1.10", room_name="Kitchen", uid="k"),
            Speaker(ip="192.168.1.11", room_name="Office", uid="o"),
        ),
        (),
    )

    async def discover(**kwargs: object) -> SonosSystem:
        return system

    monkeypatch.setattr(controller_module, "discover", discover)
    return system


def test_controller_configuration_is_read_only() -> None:
    controller = SonosController(timeout=3.0, discovery_timeout=1.5)
    assert controller.timeout == 3.0
    assert controller.discovery_timeout == 1.5
    assert controller.include_invisible is False
    assert controller.system is None
    with pytest.raises(AttributeError):
        controller.timeout = 5.0  # type: ignore[misc]


@pytest.mark.parametrize("operation", ["speaker", "speakers", "discover", "play"])
def test_controller_requires_context(operation: str) -> None:
    async def run() -> None:
        controller = SonosController()
        for _ in range(2):
            with pytest.raises(RuntimeError, match="async with SonosController"):
                await getattr(controller, operation)()
            async with controller:
                pass

    asyncio.run(run())


def test_speakers_and_aliases_share_lazy_discovery(
    monkeypatch: pytest.MonkeyPatch, household: SonosSystem
) -> None:
    calls: list[dict[str, object]] = []

    async def discover(**kwargs: object) -> SonosSystem:
        calls.append(kwargs)
        return household

    monkeypatch.setattr(controller_module, "discover", discover)

    async def run() -> None:
        async with SonosController(timeout=2, discovery_timeout=1) as sonos:
            assert calls == []
            assert await sonos.speakers() == household.speakers
            kitchen = await sonos.speaker("Kitchen")
            assert await sonos.speaker("kitchen") is kitchen
            assert await sonos.speaker("Kitch") is kitchen
            assert await sonos.speaker(ip=kitchen.ip) is kitchen
            assert sonos.system is household
            assert not kitchen.is_closed
        assert kitchen.is_closed
        assert sonos.system is None

    asyncio.run(run())
    assert calls == [{"timeout": 2, "discovery_timeout": 1, "include_invisible": False}]


def test_direct_ip_skips_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    async def discover(**kwargs: object) -> SonosSystem:
        raise AssertionError("direct IP access must not discover")

    monkeypatch.setattr(controller_module, "discover", discover)

    async def run() -> None:
        async with SonosController() as sonos:
            client = await sonos.speaker(ip="192.168.1.10")
            assert client.ip == "192.168.1.10"
            assert sonos.system is None
            with pytest.raises(ValueError, match="either"):
                await sonos.speaker("Kitchen", ip=client.ip)

    asyncio.run(run())


def test_refresh_updates_topology_and_replaces_changed_device(
    monkeypatch: pytest.MonkeyPatch, household: SonosSystem
) -> None:
    refreshed = SonosSystem(
        (Speaker(ip="192.168.1.10", room_name="Dining", uid="new"),), ()
    )

    async def discover(**kwargs: object) -> SonosSystem:
        return refreshed

    async def run() -> None:
        async with SonosController() as sonos:
            first = await sonos.speaker("Kitchen")
            monkeypatch.setattr(controller_module, "discover", discover)
            assert await sonos.discover() is refreshed
            assert await sonos.speakers() == refreshed.speakers
            second = await sonos.speaker("Dining")
            assert second is not first
            assert first.is_closed
            assert second.uid == "new"
            await second.close()
            replacement = await sonos.speaker("Dining")
            assert replacement is not second
            assert not replacement.is_closed

    asyncio.run(run())


def test_failed_refresh_preserves_cached_topology(
    monkeypatch: pytest.MonkeyPatch, household: SonosSystem
) -> None:
    async def discover(**kwargs: object) -> SonosSystem:
        raise DiscoveryError("unavailable")

    async def run() -> None:
        async with SonosController() as sonos:
            first = await sonos.speaker("Kitchen")
            monkeypatch.setattr(controller_module, "discover", discover)
            with pytest.raises(DiscoveryError):
                await sonos.discover()
            assert sonos.system is household
            assert await sonos.speaker("Kitchen") is first

    asyncio.run(run())


def test_shortcuts_reuse_clients_and_target_room_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = SonosSystem(
        (
            Speaker(ip="192.168.1.10", room_name="Kitchen", uid="k", port=1401),
            Speaker(
                ip="192.168.1.11", room_name="Office", uid="o", coordinator_uid="k"
            ),
        ),
        (),
    )
    calls: list[tuple[httpx2.AsyncClient, str, str, dict[str, object]]] = []

    async def discover(**kwargs: object) -> SonosSystem:
        return system

    async def soap(http, endpoint, service, action, args):  # type: ignore[no-untyped-def]
        assert not http.is_closed
        calls.append((http, endpoint, action, args))
        return {}

    monkeypatch.setattr(controller_module, "discover", discover)
    monkeypatch.setattr(client_module, "soap_call", soap)

    async def run() -> None:
        async with SonosController(timeout=3) as sonos:
            kitchen = await sonos.speaker("Kitchen")
            assert await sonos.speaker("Office") is kitchen
            await sonos.play("Office")
            await sonos.pause("Kitchen")
            await sonos.stop("Kitchen")
            await sonos.set_volume(30, "Office")
            office = await sonos.speaker("Office", coordinator=False)
            assert office.ip == "192.168.1.11"
            assert not kitchen.is_closed and not office.is_closed
            assert kitchen.port == 1401
            assert len({id(call[0]) for call in calls}) == 1
            assert calls[0][0].timeout.connect == 3
        assert kitchen.is_closed and office.is_closed
        assert calls[0][0].is_closed

    asyncio.run(run())
    assert [call[2] for call in calls] == ["Play", "Pause", "Stop", "SetVolume"]
    assert all("192.168.1.10:1401" in call[1] for call in calls[:3])
    assert "192.168.1.11:1400" in calls[3][1]
    assert calls[3][3]["DesiredVolume"] == "30"


def test_concurrent_first_lookups_share_discovery(
    monkeypatch: pytest.MonkeyPatch, household: SonosSystem
) -> None:
    async def run() -> None:
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def discover(**kwargs: object) -> SonosSystem:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return household

        monkeypatch.setattr(controller_module, "discover", discover)
        async with SonosController() as sonos:
            pending = [asyncio.create_task(sonos.speaker("Kitchen"))]
            try:
                await asyncio.wait_for(started.wait(), timeout=1)
                pending.extend(
                    asyncio.create_task(sonos.speaker(room))
                    for room in ("Office", "Kitchen")
                )
                pending.append(asyncio.create_task(sonos.speakers()))
                release.set()
                first, office, repeated, speakers = await asyncio.wait_for(
                    asyncio.gather(*pending), timeout=1
                )
                assert first is repeated
                assert office.ip == "192.168.1.11"
                assert speakers == household.speakers
                assert calls == 1
            finally:
                release.set()
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("cancel_first", [False, True])
def test_failed_or_cancelled_discovery_can_retry(
    monkeypatch: pytest.MonkeyPatch, household: SonosSystem, cancel_first: bool
) -> None:
    async def run() -> None:
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def discover(**kwargs: object) -> SonosSystem:
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await release.wait()
                raise DiscoveryError("temporarily unavailable")
            return household

        monkeypatch.setattr(controller_module, "discover", discover)
        async with SonosController() as sonos:
            first = asyncio.create_task(sonos.speaker("Kitchen"))
            second = None
            try:
                await asyncio.wait_for(started.wait(), timeout=1)
                second = asyncio.create_task(sonos.speaker("Kitchen"))
                if cancel_first:
                    first.cancel()
                else:
                    release.set()
                with pytest.raises(
                    asyncio.CancelledError if cancel_first else DiscoveryError
                ):
                    await first
                client = await asyncio.wait_for(second, timeout=1)
                assert client.ip == "192.168.1.10"
                assert calls == 2
            finally:
                first.cancel()
                if second is not None:
                    second.cancel()
                await asyncio.gather(
                    first,
                    *(() if second is None else (second,)),
                    return_exceptions=True,
                )

    asyncio.run(run())


def test_controller_reentry_and_nested_context(household: SonosSystem) -> None:
    async def run() -> None:
        controller = SonosController()
        async with controller:
            first = await controller.speaker("Kitchen")
            with pytest.raises(RuntimeError, match="already open"):
                async with controller:
                    pass
            assert not first.is_closed
        assert first.is_closed and first._http.is_closed
        await controller.close()
        async with controller:
            second = await controller.speaker("Kitchen")
            assert second is not first
            assert second._http is not first._http
        assert second.is_closed and second._http.is_closed

    asyncio.run(run())


def test_controller_closes_all_resources_even_when_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch, household: SonosSystem
) -> None:
    closed: list[str] = []

    async def close(websocket: object) -> None:
        closed.append("websocket")
        if len(closed) == 1:
            raise RuntimeError("cleanup failed")

    monkeypatch.setattr(client_module.AudioClipWebSocket, "close", close)

    async def run() -> None:
        with pytest.raises(RuntimeError, match="cleanup failed"):
            async with SonosController() as sonos:
                first = await sonos.speaker("Kitchen")
                second = await sonos.speaker("Office")
        assert first.is_closed and second.is_closed
        assert first._http.is_closed
        assert len(closed) == 2
        await sonos.close()

    asyncio.run(run())


def test_controller_closes_clients_on_body_error() -> None:
    async def run() -> None:
        with pytest.raises(RuntimeError, match="command failed"):
            async with SonosController() as sonos:
                client = await sonos.speaker(ip="192.168.1.10")
                raise RuntimeError("command failed")
        assert client.is_closed and client._http.is_closed

    asyncio.run(run())


@pytest.mark.parametrize("close_controller_early", [False, True])
def test_watch_closes_subscription_and_preserves_managed_client(
    monkeypatch: pytest.MonkeyPatch, close_controller_early: bool
) -> None:
    class Watcher:
        started = False
        closes = 0

        async def start(self) -> None:
            self.started = True

        async def close(self) -> None:
            self.closes += 1

    watcher = Watcher()
    options: dict[str, object] = {}

    def watch(self: object, **kwargs: object) -> Watcher:
        options.update(kwargs)
        return watcher

    monkeypatch.setattr(client_module.SonosClient, "watch", watch)

    async def run() -> None:
        async with SonosController() as sonos:
            client = await sonos.speaker(ip="192.168.1.10")
            async with sonos.watch(ip=client.ip, callback_port=1234) as active:
                assert active is watcher and watcher.started
                if close_controller_early:
                    await sonos.close()
                    assert watcher.closes == 1 and client.is_closed
            assert watcher.closes == 1
            if not close_controller_early:
                assert await sonos.speaker(ip=client.ip) is client
                assert not client.is_closed
        assert client.is_closed
        assert options["callback_port"] == 1234

    asyncio.run(run())
