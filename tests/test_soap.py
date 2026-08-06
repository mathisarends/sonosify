import asyncio

import httpx
import pytest

from sonosify.errors import NetworkError, UPnPError
from sonosify.soap import soap_call


def _client(
    handler: httpx.MockTransport | None = None, **kwargs: object
) -> httpx.AsyncClient:
    transport = handler or httpx.MockTransport(lambda request: httpx.Response(200))
    return httpx.AsyncClient(transport=transport, **kwargs)


def test_soap_call_sorts_and_escapes_envelope_args() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            text=(
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
                "<s:Body></s:Body></s:Envelope>"
            ),
        )

    async def run() -> None:
        async with _client(httpx.MockTransport(handler)) as client:
            await soap_call(
                client,
                "http://host/Control",
                "urn:test",
                "DoThing",
                {"B": "x&y", "A": "1"},
            )

    asyncio.run(run())

    envelope = requests[0].content.decode()
    assert envelope.index("<A>1</A>") < envelope.index("<B>x&amp;y</B>")
    assert requests[0].headers["SOAPACTION"] == '"urn:test#DoThing"'


def test_soap_call_parses_successful_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["SOAPACTION"] == '"urn:test#GetVolume"'
        return httpx.Response(
            200,
            text=(
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
                '<s:Body><u:GetVolumeResponse xmlns:u="urn:test">'
                "<CurrentVolume>23</CurrentVolume>"
                "</u:GetVolumeResponse></s:Body></s:Envelope>"
            ),
        )

    async def run() -> dict[str, str]:
        async with _client(httpx.MockTransport(handler)) as client:
            return await soap_call(
                client, "http://host/Control", "urn:test", "GetVolume"
            )

    assert asyncio.run(run()) == {"CurrentVolume": "23"}


def test_soap_call_raises_upnp_error_on_server_fault() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            text=(
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
                "<s:Body><s:Fault><detail>"
                '<UPnPError xmlns="urn:schemas-upnp-org:control-1-0">'
                "<errorCode>701</errorCode>"
                "<errorDescription>Transition not available</errorDescription>"
                "</UPnPError></detail></s:Fault></s:Body></s:Envelope>"
            ),
        )

    async def run() -> None:
        async with _client(httpx.MockTransport(handler)) as client:
            await soap_call(client, "http://host/Control", "urn:test", "Play")

    with pytest.raises(UPnPError) as excinfo:
        asyncio.run(run())
    assert excinfo.value.code == "701"
    assert "Transition not available" in str(excinfo.value)
    with pytest.raises(AttributeError):
        excinfo.value.code = "0"  # type: ignore[misc]


def test_soap_call_raises_http_error_when_fault_has_no_upnp_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            text=(
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
                "<s:Body><s:Fault><detail>unexpected</detail></s:Fault></s:Body>"
                "</s:Envelope>"
            ),
        )

    async def run() -> None:
        async with _client(httpx.MockTransport(handler)) as client:
            await soap_call(client, "http://host/Control", "urn:test", "Play")

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())


def test_soap_call_raises_http_error_for_unparseable_server_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    async def run() -> None:
        async with _client(httpx.MockTransport(handler)) as client:
            await soap_call(client, "http://host/Control", "urn:test", "Play")

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())


def test_soap_call_translates_network_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    async def run() -> None:
        async with _client(httpx.MockTransport(handler)) as client:
            await soap_call(client, "http://host/Control", "urn:test", "Play")

    with pytest.raises(NetworkError, match="timed out"):
        asyncio.run(run())
