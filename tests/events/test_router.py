import asyncio
import logging

import pytest

from sonosify.events import (
    AVTransportEvent,
    EventRouter,
    QueueEvent,
    RenderingControlEvent,
    SonosEvent,
    UnknownSonosEvent,
)


def _dispatch(router: EventRouter, *events: SonosEvent) -> None:
    async def run() -> None:
        for event in events:
            await router.dispatch(event)

    asyncio.run(run())


def test_handler_only_receives_its_registered_event_type() -> None:
    router = EventRouter()
    seen: list[SonosEvent] = []

    @router.on(AVTransportEvent)
    def handle(event: AVTransportEvent) -> None:
        seen.append(event)

    _dispatch(router, AVTransportEvent(), RenderingControlEvent())

    assert seen == [AVTransportEvent()]


def test_handler_can_register_for_several_event_types() -> None:
    router = EventRouter()
    seen: list[str] = []

    @router.on(RenderingControlEvent, QueueEvent)
    def handle(event: SonosEvent) -> None:
        seen.append(event.service)

    _dispatch(router, RenderingControlEvent(), QueueEvent(), AVTransportEvent())

    assert seen == ["rendering_control", "queue"]


def test_bare_decorator_receives_every_event() -> None:
    router = EventRouter()
    seen: list[SonosEvent] = []

    @router.on()
    def handle(event: SonosEvent) -> None:
        seen.append(event)

    _dispatch(router, AVTransportEvent(), UnknownSonosEvent(service="nonexistent"))

    assert len(seen) == 2


def test_async_handlers_are_awaited() -> None:
    router = EventRouter()
    seen: list[int] = []

    @router.on(AVTransportEvent)
    async def handle(event: AVTransportEvent) -> None:
        await asyncio.sleep(0)
        seen.append(1)

    _dispatch(router, AVTransportEvent())

    assert seen == [1]


def test_handlers_run_in_registration_order() -> None:
    router = EventRouter()
    order: list[str] = []

    @router.on()
    def first(event: SonosEvent) -> None:
        order.append("first")

    @router.on(AVTransportEvent)
    async def second(event: AVTransportEvent) -> None:
        order.append("second")

    _dispatch(router, AVTransportEvent())

    assert order == ["first", "second"]


def test_failing_handler_does_not_stop_the_remaining_handlers() -> None:
    router = EventRouter()
    seen: list[str] = []

    @router.on()
    def broken(event: SonosEvent) -> None:
        raise RuntimeError("boom")

    @router.on()
    async def broken_async(event: SonosEvent) -> None:
        raise RuntimeError("boom async")

    @router.on()
    def survivor(event: SonosEvent) -> None:
        seen.append(event.service)

    _dispatch(router, AVTransportEvent(), RenderingControlEvent())

    assert seen == ["av_transport", "rendering_control"]


def test_failing_handler_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    router = EventRouter()

    @router.on()
    def broken(event: SonosEvent) -> None:
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger="sonosify.events"):
        _dispatch(router, AVTransportEvent())

    assert "broken" in caplog.text
    assert "boom" in caplog.text


def test_handler_cancellation_still_propagates() -> None:
    router = EventRouter()

    @router.on()
    async def cancelled(event: SonosEvent) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        _dispatch(router, AVTransportEvent())


def test_decorator_returns_the_original_handler() -> None:
    router = EventRouter()

    def handle(event: AVTransportEvent) -> None:
        return None

    assert router.on(AVTransportEvent)(handle) is handle
