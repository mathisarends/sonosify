from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable

import httpx
import pytest

import sonosify.events.subscription as subscription_module
from sonosify.errors import SubscriptionError
from sonosify.events import AVTransportEvent, EventService, EventSubscription


class _FakeHttpClient:
    """Stands in for the httpx.AsyncClient used for SUBSCRIBE/UNSUBSCRIBE."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.renew_status = 200
        self.unimplemented: set[str] = set()
        self._sid_counter = 0

    @property
    def renewals(self) -> list[tuple[str, str, dict[str, str]]]:
        return [request for request in self.requests if "SID" in request[2]]

    async def request(
        self, method: str, url: str, *, headers: dict[str, str]
    ) -> httpx.Response:
        self.requests.append((method, url, headers))
        request = httpx.Request(method, url)
        if method != "SUBSCRIBE":
            return httpx.Response(200, request=request)
        if any(path in url for path in self.unimplemented):
            raise httpx.HTTPStatusError(
                "service unavailable",
                request=request,
                response=httpx.Response(503, request=request),
            )
        if "SID" in headers and self.renew_status != 200:
            raise httpx.HTTPStatusError(
                "renewal rejected",
                request=request,
                response=httpx.Response(self.renew_status, request=request),
            )
        self._sid_counter += 1
        return httpx.Response(
            200, headers={"SID": f"uuid:sub-{self._sid_counter}"}, request=request
        )

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch) -> _FakeHttpClient:
    fake = _FakeHttpClient()
    monkeypatch.setattr(subscription_module.httpx, "AsyncClient", lambda **kwargs: fake)
    monkeypatch.setattr(
        subscription_module, "_local_ip_for", lambda remote_ip: "127.0.0.1"
    )
    return fake


def _send_notify(port: int, *, sid: str, path: str, body: bytes) -> None:
    async def send() -> None:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        request = (
            f"NOTIFY {path} HTTP/1.1\r\n"
            f"SID: {sid}\r\n"
            "Content-Length: "
            f"{len(body)}\r\n\r\n"
        ).encode() + body
        writer.write(request)
        await writer.drain()
        await reader.read()
        writer.close()
        await writer.wait_closed()

    asyncio.run(send())


def test_start_subscribes_to_each_configured_service(
    fake_http: _FakeHttpClient,
) -> None:
    async def run() -> None:
        subscription = EventSubscription(
            "192.168.1.10", services=(EventService.AV_TRANSPORT,)
        )
        await subscription.start()
        try:
            assert len(fake_http.requests) == 1
            method, url, headers = fake_http.requests[0]
            assert method == "SUBSCRIBE"
            assert url == "http://192.168.1.10:1400/MediaRenderer/AVTransport/Event"
            assert headers["NT"] == "upnp:event"
            assert "CALLBACK" in headers
        finally:
            await subscription.close()

    asyncio.run(run())


def test_start_is_idempotent(fake_http: _FakeHttpClient) -> None:
    async def run() -> None:
        subscription = EventSubscription(
            "192.168.1.10", services=(EventService.AV_TRANSPORT,)
        )
        await subscription.start()
        await subscription.start()
        await subscription.close()

    asyncio.run(run())

    subscribe_calls = [r for r in fake_http.requests if r[0] == "SUBSCRIBE"]
    assert len(subscribe_calls) == 1


def test_close_unsubscribes_all_services(fake_http: _FakeHttpClient) -> None:
    async def run() -> None:
        subscription = EventSubscription(
            "192.168.1.10",
            services=(EventService.AV_TRANSPORT, EventService.RENDERING_CONTROL),
        )
        await subscription.start()
        await subscription.close()

    asyncio.run(run())

    methods = [request[0] for request in fake_http.requests]
    assert methods.count("SUBSCRIBE") == 2
    assert methods.count("UNSUBSCRIBE") == 2


def test_callback_server_rejects_non_notify_methods(
    fake_http: _FakeHttpClient,
) -> None:
    async def send_get(port: int) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /MediaRenderer/AVTransport/Event HTTP/1.1\r\n\r\n")
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
        return response

    async def run() -> bytes:
        subscription = EventSubscription(
            "192.168.1.10",
            services=(EventService.AV_TRANSPORT,),
            callback_host="127.0.0.1",
        )
        await subscription.start()
        assert subscription.callback_host == "127.0.0.1"
        try:
            port = subscription._server.sockets[0].getsockname()[1]  # noqa: SLF001
            return await send_get(port)
        finally:
            await subscription.close()

    response = asyncio.run(run())

    assert response.startswith(b"HTTP/1.1 405 Method Not Allowed")


def test_callback_port_exposes_the_requested_port() -> None:
    subscription = EventSubscription(
        "192.168.1.10", services=(EventService.AV_TRANSPORT,), callback_port=12345
    )

    assert subscription.callback_port == 12345


def test_local_ip_for_returns_outbound_interface_address() -> None:
    local_ip = subscription_module._local_ip_for("8.8.8.8")

    assert local_ip.count(".") == 3


def test_notify_request_is_parsed_and_queued(fake_http: _FakeHttpClient) -> None:
    body = (
        b'<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
        b"<e:property><LastChange>"
        b"&lt;Event xmlns=&quot;urn:schemas-upnp-org:metadata-1-0/AVT/&quot;&gt;"
        b"&lt;InstanceID val=&quot;0&quot;&gt;"
        b"&lt;TransportState val=&quot;PLAYING&quot;/&gt;"
        b"&lt;/InstanceID&gt;&lt;/Event&gt;"
        b"</LastChange></e:property>"
        b"</e:propertyset>"
    )

    async def run() -> object:
        subscription = EventSubscription(
            "192.168.1.10", services=(EventService.AV_TRANSPORT,)
        )
        await subscription.start()
        try:
            path = next(iter(subscription._callback_paths))  # noqa: SLF001
            port = subscription._server.sockets[0].getsockname()[1]  # noqa: SLF001
            await asyncio.to_thread(
                _send_notify, port, sid="uuid:sub-1", path=path, body=body
            )
            return await subscription.next_event(timeout=2)
        finally:
            await subscription.close()

    event = asyncio.run(run())

    assert event.service == EventService.AV_TRANSPORT
    assert event.transport_state.value == "PLAYING"


def test_events_iterator_yields_queued_events(fake_http: _FakeHttpClient) -> None:
    body = (
        b'<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
        b"<e:property><ZoneName>Kitchen</ZoneName></e:property>"
        b"</e:propertyset>"
    )

    async def run() -> object:
        subscription = EventSubscription(
            "192.168.1.10", services=(EventService.AV_TRANSPORT,)
        )
        await subscription.start()
        try:
            path = next(iter(subscription._callback_paths))  # noqa: SLF001
            port = subscription._server.sockets[0].getsockname()[1]  # noqa: SLF001
            await asyncio.to_thread(
                _send_notify, port, sid="uuid:sub-1", path=path, body=body
            )
            async for event in subscription.events(timeout=2):
                return event
        finally:
            await subscription.close()
        raise AssertionError("no event received")

    event = asyncio.run(run())

    assert event.values == {"ZoneName": "Kitchen"}


def test_async_context_manager_starts_and_closes(fake_http: _FakeHttpClient) -> None:
    async def run() -> bool:
        async with EventSubscription(
            "192.168.1.10", services=(EventService.AV_TRANSPORT,)
        ) as subscription:
            assert subscription._server is not None  # noqa: SLF001
        return subscription._server is None  # noqa: SLF001

    assert asyncio.run(run()) is True


def test_unknown_service_is_rejected_before_any_request(
    fake_http: _FakeHttpClient,
) -> None:
    with pytest.raises(ValueError, match="unsupported event service"):
        EventSubscription("192.168.1.10", services=("nonexistent",))

    assert fake_http.requests == []


def test_services_the_player_does_not_implement_are_skipped(
    fake_http: _FakeHttpClient,
) -> None:
    fake_http.unimplemented = {"/HTControl/Event"}

    async def run() -> tuple[EventService, ...]:
        async with EventSubscription(
            "192.168.1.10",
            services=(EventService.HT_CONTROL, EventService.AV_TRANSPORT),
        ) as subscription:
            assert subscription.services == (
                EventService.HT_CONTROL,
                EventService.AV_TRANSPORT,
            )
            return subscription.subscribed_services

    assert asyncio.run(run()) == (EventService.AV_TRANSPORT,)


def test_start_fails_when_no_service_accepts_the_subscription(
    fake_http: _FakeHttpClient,
) -> None:
    fake_http.unimplemented = {"/HTControl/Event"}

    async def run() -> None:
        async with EventSubscription(
            "192.168.1.10", services=(EventService.HT_CONTROL,)
        ):
            pass

    with pytest.raises(SubscriptionError) as error:
        asyncio.run(run())

    assert error.value.services == (EventService.HT_CONTROL,)
    assert isinstance(error.value.__cause__, httpx.HTTPStatusError)


def test_skipped_service_is_not_renewed(
    fake_http: _FakeHttpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subscription_module, "_MIN_RENEW_INTERVAL", 0.01)
    fake_http.unimplemented = {"/HTControl/Event"}

    async def run() -> None:
        async with EventSubscription(
            "192.168.1.10",
            services=(EventService.HT_CONTROL, EventService.AV_TRANSPORT),
            timeout_seconds=0,
        ):
            await _until(lambda: bool(fake_http.renewals))

    asyncio.run(run())

    assert all("/HTControl/" not in url for _, url, _ in fake_http.renewals)


def test_run_dispatches_events_to_registered_handlers(
    fake_http: _FakeHttpClient,
) -> None:
    body = (
        b'<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
        b"<e:property><LastChange>"
        b"&lt;Event xmlns=&quot;urn:schemas-upnp-org:metadata-1-0/AVT/&quot;&gt;"
        b"&lt;InstanceID val=&quot;0&quot;&gt;"
        b"&lt;TransportState val=&quot;PLAYING&quot;/&gt;"
        b"&lt;/InstanceID&gt;&lt;/Event&gt;"
        b"</LastChange></e:property>"
        b"</e:propertyset>"
    )

    async def run() -> list[AVTransportEvent]:
        seen: list[AVTransportEvent] = []
        received = asyncio.Event()
        async with EventSubscription(
            "192.168.1.10", services=(EventService.AV_TRANSPORT,)
        ) as subscription:

            @subscription.on(AVTransportEvent)
            def collect(event: AVTransportEvent) -> None:
                seen.append(event)
                received.set()

            dispatcher = asyncio.create_task(subscription.run())
            path = next(iter(subscription._callback_paths))  # noqa: SLF001
            port = subscription._server.sockets[0].getsockname()[1]  # noqa: SLF001
            await asyncio.to_thread(
                _send_notify, port, sid="uuid:sub-1", path=path, body=body
            )
            await asyncio.wait_for(received.wait(), timeout=2)
            dispatcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatcher
        return seen

    seen = asyncio.run(run())

    assert [event.transport_state for event in seen] == ["PLAYING"]


def test_subscriptions_are_renewed_before_they_lapse(
    fake_http: _FakeHttpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subscription_module, "_MIN_RENEW_INTERVAL", 0.01)

    async def run() -> None:
        async with EventSubscription(
            "192.168.1.10", services=(EventService.AV_TRANSPORT,), timeout_seconds=0
        ):
            await _until(lambda: bool(fake_http.renewals))

    asyncio.run(run())

    _, url, headers = fake_http.renewals[0]
    assert url == "http://192.168.1.10:1400/MediaRenderer/AVTransport/Event"
    assert headers["SID"] == "uuid:sub-1"
    assert "CALLBACK" not in headers


def test_rejected_renewal_falls_back_to_a_fresh_subscription(
    fake_http: _FakeHttpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subscription_module, "_MIN_RENEW_INTERVAL", 0.01)
    fake_http.renew_status = 412

    async def run() -> str:
        async with EventSubscription(
            "192.168.1.10", services=(EventService.AV_TRANSPORT,), timeout_seconds=0
        ) as subscription:
            await _until(lambda: bool(fake_http.renewals))
            await _until(
                lambda: (
                    subscription._subscriptions  # noqa: SLF001
                    != {EventService.AV_TRANSPORT: "uuid:sub-1"}
                )
            )
            return subscription._subscriptions[EventService.AV_TRANSPORT]  # noqa: SLF001

    assert asyncio.run(run()) == "uuid:sub-2"


async def _until(condition: Callable[[], bool], *, timeout: float = 2.0) -> None:
    async def wait() -> None:
        while not condition():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout=timeout)
