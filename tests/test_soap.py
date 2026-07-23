import asyncio

import httpx
import pytest

from sonosify.errors import NetworkError, UPnPError
from sonosify.soap import build_envelope, parse_response, parse_upnp_error, soap_call


def test_build_envelope_sorts_and_escapes_args() -> None:
    envelope = build_envelope("urn:test", "DoThing", {"B": "x&y", "A": "1"})

    assert envelope.index("<A>1</A>") < envelope.index("<B>x&amp;y</B>")
    assert "SOAPACTION" not in envelope


def test_parse_response_reads_direct_children() -> None:
    raw = """
    <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
      <s:Body>
        <u:GetVolumeResponse xmlns:u="urn:test">
          <CurrentVolume>23</CurrentVolume>
        </u:GetVolumeResponse>
      </s:Body>
    </s:Envelope>
    """

    assert parse_response(raw) == {"CurrentVolume": "23"}


def test_parse_upnp_error() -> None:
    raw = """
    <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
      <s:Body><s:Fault><detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0">
        <errorCode>701</errorCode><errorDescription>Transition not available</errorDescription>
      </UPnPError></detail></s:Fault></s:Body>
    </s:Envelope>
    """

    error = parse_upnp_error(raw)

    assert error is not None
    assert error.code == "701"
    assert "Transition not available" in str(error)
    with pytest.raises(AttributeError):
        error.code = "0"  # type: ignore[misc]


def test_parse_upnp_error_returns_none_for_non_upnp_fault() -> None:
    assert parse_upnp_error("<s:Envelope/>") is None
    assert parse_upnp_error("<not valid xml") is None


def _client(
    handler: httpx.MockTransport | None = None, **kwargs: object
) -> httpx.AsyncClient:
    transport = handler or httpx.MockTransport(lambda request: httpx.Response(200))
    return httpx.AsyncClient(transport=transport, **kwargs)


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
