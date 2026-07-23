from __future__ import annotations

import asyncio

import pytest

import sonosify.controller as controller_module
from sonosify import AVTransportEvent, SonosController, TransportState
from sonosify.models import Group, Speaker
from sonosify.topology import SonosSystem


class _FakeWatcher:
    def __init__(self, events: list[object]) -> None:
        self.ip = "192.168.1.10"
        self._events = list(events)
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> _FakeWatcher:
        self.entered = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.exited = True

    def __aiter__(self) -> _FakeWatcher:
        return self

    async def __anext__(self) -> object:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


class _FakeClient:
    def __init__(self, watcher: _FakeWatcher) -> None:
        self._watcher = watcher
        self.closed = False
        self.watch_kwargs: dict[str, object] | None = None

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.closed = True

    def watch(self, **kwargs: object) -> _FakeWatcher:
        self.watch_kwargs = kwargs
        return self._watcher


def test_controller_watch_flattens_client_and_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [AVTransportEvent(values={}, transport_state=TransportState.PLAYING)]
    watcher = _FakeWatcher(events)
    client = _FakeClient(watcher)

    controller = SonosController()

    async def fake_client(  # type: ignore[no-untyped-def]
        _controller, room=None, *, ip=None, coordinator=True
    ):
        return client

    monkeypatch.setattr(SonosController, "client", fake_client)

    async def run() -> list[object]:
        seen: list[object] = []
        async with controller.watch("Kitchen") as active:
            assert active is watcher
            async for event in active:
                seen.append(event)
        return seen

    seen = asyncio.run(run())

    assert seen == events
    assert watcher.entered and watcher.exited
    assert client.closed


def test_controller_configuration_is_read_only() -> None:
    controller = SonosController(timeout=3.0, discovery_timeout=1.5)

    assert controller.timeout == 3.0
    assert controller.discovery_timeout == 1.5
    assert controller.include_invisible is False
    assert controller.system is None
    with pytest.raises(AttributeError):
        controller.timeout = 5.0  # type: ignore[misc]


def test_controller_discover_caches_system(monkeypatch: pytest.MonkeyPatch) -> None:
    speaker = Speaker(ip="192.168.1.10", room_name="Kitchen", uid="k")
    system = SonosSystem(
        (speaker,), (Group(id="g", coordinator_uid="k", members=(speaker,)),)
    )

    calls: list[dict[str, object]] = []

    async def fake_discover(*, timeout, discovery_timeout, include_invisible):  # type: ignore[no-untyped-def]
        calls.append(
            {
                "timeout": timeout,
                "discovery_timeout": discovery_timeout,
                "include_invisible": include_invisible,
            }
        )
        return system

    monkeypatch.setattr(controller_module, "discover", fake_discover)

    controller = SonosController(timeout=2.0, discovery_timeout=1.0)
    result = asyncio.run(controller.discover())

    assert result is system
    assert controller.system is system
    assert calls == [
        {"timeout": 2.0, "discovery_timeout": 1.0, "include_invisible": False}
    ]


def test_controller_client_reuses_cached_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    speaker = Speaker(
        ip="192.168.1.10", room_name="Kitchen", uid="k", is_coordinator=True
    )
    system = SonosSystem((speaker,), ())

    async def fail_discover(*args: object, **kwargs: object) -> SonosSystem:
        raise AssertionError("discover() should not be called when system is cached")

    monkeypatch.setattr(controller_module, "discover", fail_discover)

    controller = SonosController()
    controller._system = system  # noqa: SLF001 - seeding the cache for the test

    client = asyncio.run(controller.client("Kitchen"))

    assert client.ip == "192.168.1.10"


def test_controller_client_triggers_discovery_when_uncached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    speaker = Speaker(
        ip="192.168.1.10", room_name="Kitchen", uid="k", is_coordinator=True
    )
    system = SonosSystem((speaker,), ())

    async def fake_discover(*, timeout, discovery_timeout, include_invisible):  # type: ignore[no-untyped-def]
        return system

    monkeypatch.setattr(controller_module, "discover", fake_discover)

    controller = SonosController()
    client = asyncio.run(controller.client("Kitchen"))

    assert client.ip == "192.168.1.10"
    assert controller.system is system


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __aenter__(self) -> _RecordingClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def play(self) -> None:
        self.calls.append("play")

    async def pause(self) -> None:
        self.calls.append("pause")

    async def stop(self) -> None:
        self.calls.append("stop")

    async def set_volume(self, volume: int) -> None:
        self.calls.append(f"set_volume:{volume}")


@pytest.mark.parametrize(
    ("method", "call_args", "expected"),
    [
        ("play", (), "play"),
        ("pause", (), "pause"),
        ("stop", (), "stop"),
    ],
)
def test_controller_convenience_playback_methods(
    monkeypatch: pytest.MonkeyPatch, method: str, call_args: tuple, expected: str
) -> None:
    recording_client = _RecordingClient()

    async def fake_client(self, room=None, *, ip=None, coordinator=True):  # type: ignore[no-untyped-def]
        return recording_client

    monkeypatch.setattr(SonosController, "client", fake_client)

    controller = SonosController()
    asyncio.run(getattr(controller, method)("Kitchen", *call_args))

    assert recording_client.calls == [expected]


def test_controller_set_volume_targets_non_coordinator_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording_client = _RecordingClient()
    seen_kwargs: dict[str, object] = {}

    async def fake_client(self, room=None, *, ip=None, coordinator=True):  # type: ignore[no-untyped-def]
        seen_kwargs["coordinator"] = coordinator
        return recording_client

    monkeypatch.setattr(SonosController, "client", fake_client)

    controller = SonosController()
    asyncio.run(controller.set_volume(30, "Kitchen"))

    assert recording_client.calls == ["set_volume:30"]
    assert seen_kwargs["coordinator"] is False
