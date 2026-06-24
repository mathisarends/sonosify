import asyncio

from sonosify import AVTransportEvent, SonosController, TransportState


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


def test_controller_watch_flattens_client_and_subscription() -> None:
    events = [AVTransportEvent(values={}, transport_state=TransportState.PLAYING)]
    watcher = _FakeWatcher(events)
    client = _FakeClient(watcher)

    controller = SonosController()

    async def fake_client(room=None, *, ip=None, coordinator=True):  # type: ignore[no-untyped-def]
        return client

    controller.client = fake_client  # type: ignore[method-assign]

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
