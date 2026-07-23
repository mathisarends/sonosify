from __future__ import annotations

import asyncio

import httpx
import pytest

import sonosify.events.subscription as subscription_module
from sonosify.events import EventService, EventSubscription


class _FakeHttpClient:
    """Stands in for the httpx.AsyncClient used for SUBSCRIBE/UNSUBSCRIBE."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self._sid_counter = 0

    async def request(
        self, method: str, url: str, *, headers: dict[str, str]
    ) -> httpx.Response:
        self.requests.append((method, url, headers))
        if method == "SUBSCRIBE":
            self._sid_counter += 1
            return httpx.Response(
                200,
                headers={"SID": f"uuid:sub-{self._sid_counter}"},
                request=httpx.Request(method, url),
            )
        return httpx.Response(200, request=httpx.Request(method, url))

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
