from __future__ import annotations

import asyncio
from html import escape

import httpx
import pytest

import sonosify.discovery as discovery_module
from sonosify.discovery import discover
from sonosify.errors import DiscoveryError

_KITCHEN_XML = (
    '<root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
    "<roomName>Kitchen</roomName><UDN>uuid:RINCON_KITCHEN</UDN>"
    "</device></root>"
)
_OFFICE_XML = (
    '<root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
    "<roomName>Office</roomName><UDN>uuid:RINCON_OFFICE</UDN>"
    "</device></root>"
)


def _zone_group_state(*, invisible_office: bool = False) -> str:
    invisible = "1" if invisible_office else "0"
    return (
        "<ZoneGroupState><ZoneGroups>"
        '<ZoneGroup Coordinator="RINCON_KITCHEN" ID="RINCON_KITCHEN:1">'
        '<ZoneGroupMember UUID="RINCON_KITCHEN" '
        'Location="http://192.168.1.10:1400/xml/device.xml" ZoneName="Kitchen"/>'
        f'<ZoneGroupMember UUID="RINCON_OFFICE" Invisible="{invisible}" '
        'Location="http://192.168.1.11:1400/xml/device.xml" ZoneName="Office"/>'
        "</ZoneGroup>"
        "</ZoneGroups></ZoneGroupState>"
    )


def _soap_response(body: str) -> str:
    return (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<s:Body>{body}</s:Body></s:Envelope>"
    )


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient at the network boundary discover() uses."""

    def __init__(self, handler, **kwargs: object) -> None:
        self._handler = handler

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        response = self._handler("GET", url, None)
        response.request = httpx.Request("GET", url)
        return response

    async def post(self, url: str, *, content: str, **kwargs: object) -> httpx.Response:
        response = self._handler("POST", url, content)
        response.request = httpx.Request("POST", url)
        return response


def _install_fake_network(
    monkeypatch: pytest.MonkeyPatch,
    *,
    locations: set[str],
    device_xml: dict[str, str],
    zone_group_state: str | None,
) -> None:
    def fake_ssdp_locations(timeout: float) -> set[str]:
        return locations

    def handler(method: str, url: str, body: str | None) -> httpx.Response:
        if method == "GET":
            return httpx.Response(200, text=device_xml[url])
        assert zone_group_state is not None, "unexpected SOAP call"
        response_body = (
            '<u:GetZoneGroupStateResponse xmlns:u="urn:schemas-upnp-org:'
            'service:ZoneGroupTopology:1">'
            f"<ZoneGroupState>{escape(zone_group_state)}</ZoneGroupState>"
            "</u:GetZoneGroupStateResponse>"
        )
        return httpx.Response(200, text=_soap_response(response_body))

    monkeypatch.setattr(discovery_module, "_ssdp_locations", fake_ssdp_locations)
    monkeypatch.setattr(
        discovery_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(handler, **kwargs),
    )


def test_discover_raises_when_no_ssdp_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_network(
        monkeypatch, locations=set(), device_xml={}, zone_group_state=None
    )

    with pytest.raises(DiscoveryError, match="no Sonos speakers discovered"):
        asyncio.run(discover())


def test_discover_raises_when_device_xml_unparseable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_network(
        monkeypatch,
        locations={"http://192.168.1.10:1400/xml/device.xml"},
        device_xml={"http://192.168.1.10:1400/xml/device.xml": "not xml"},
        zone_group_state=None,
    )

    with pytest.raises(DiscoveryError, match="no device metadata"):
        asyncio.run(discover())


def test_discover_builds_system_from_topology(monkeypatch: pytest.MonkeyPatch) -> None:
    locations = {
        "http://192.168.1.10:1400/xml/device.xml",
        "http://192.168.1.11:1400/xml/device.xml",
    }
    device_xml = {
        "http://192.168.1.10:1400/xml/device.xml": _KITCHEN_XML,
        "http://192.168.1.11:1400/xml/device.xml": _OFFICE_XML,
    }
    _install_fake_network(
        monkeypatch,
        locations=locations,
        device_xml=device_xml,
        zone_group_state=_zone_group_state(),
    )

    system = asyncio.run(discover())

    assert {speaker.room_name for speaker in system.speakers} == {"Kitchen", "Office"}
    assert len(system.groups) == 1
    group = system.groups[0]
    assert group.coordinator is not None
    assert group.coordinator.room_name == "Kitchen"


def test_discover_falls_back_to_one_group_per_speaker_without_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locations = {"http://192.168.1.10:1400/xml/device.xml"}
    device_xml = {"http://192.168.1.10:1400/xml/device.xml": _KITCHEN_XML}
    _install_fake_network(
        monkeypatch, locations=locations, device_xml=device_xml, zone_group_state=""
    )

    system = asyncio.run(discover())

    assert len(system.speakers) == 1
    assert len(system.groups) == 1
    assert system.groups[0].coordinator_uid == "RINCON_KITCHEN"


def test_discover_excludes_invisible_speakers_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locations = {
        "http://192.168.1.10:1400/xml/device.xml",
        "http://192.168.1.11:1400/xml/device.xml",
    }
    device_xml = {
        "http://192.168.1.10:1400/xml/device.xml": _KITCHEN_XML,
        "http://192.168.1.11:1400/xml/device.xml": _OFFICE_XML,
    }
    _install_fake_network(
        monkeypatch,
        locations=locations,
        device_xml=device_xml,
        zone_group_state=_zone_group_state(invisible_office=True),
    )

    system = asyncio.run(discover())
    assert {speaker.room_name for speaker in system.speakers} == {"Kitchen"}

    system_with_invisible = asyncio.run(discover(include_invisible=True))
    assert {speaker.room_name for speaker in system_with_invisible.speakers} == {
        "Kitchen",
        "Office",
    }


@pytest.mark.parametrize(
    "group_attributes, member_attributes",
    [
        ('ID="group-1"', 'UUID="speaker-1" Location="http://192.168.1.10:1400"'),
        (
            'ID="group-1" Coordinator="speaker-1"',
            'Location="http://192.168.1.10:1400"',
        ),
    ],
)
def test_parse_topology_rejects_missing_required_attributes(
    group_attributes: str, member_attributes: str
) -> None:
    state = (
        f"<ZoneGroupState><ZoneGroup {group_attributes}>"
        f"<ZoneGroupMember {member_attributes}/></ZoneGroup></ZoneGroupState>"
    )

    assert discovery_module._parse_topology(state, {}) is None


def test_ssdp_searches_all_local_ipv4_interfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    addresses = ("192.168.178.71", "192.168.56.1")
    responses = {
        addresses[0]: b"HTTP/1.1 200 OK\r\nLOCATION: http://speaker/device.xml\r\n\r\n",
        addresses[1]: b"HTTP/1.1 200 OK\r\n\r\n",
    }

    class FakeSocket:
        def __init__(self) -> None:
            self.address = ""
            self.closed = False

        def bind(self, address: tuple[str, int]) -> None:
            self.address = address[0]

        def setsockopt(self, *args: object) -> None:
            return None

        def setblocking(self, value: bool) -> None:
            assert value is False

        def sendto(self, message: bytes, address: tuple[str, int]) -> None:
            assert message == discovery_module._SSDP_SEARCH_MESSAGE
            assert address == discovery_module._SSDP_ADDRESS

        def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]:
            return responses[self.address], (self.address, 1900)

        def close(self) -> None:
            self.closed = True

    sockets: list[FakeSocket] = []

    def socket_factory(*args: object) -> FakeSocket:
        sock = FakeSocket()
        sockets.append(sock)
        return sock

    select_calls = 0

    def fake_select(
        readable: list[FakeSocket],
        writable: list[FakeSocket],
        exceptional: list[FakeSocket],
        timeout: float,
    ) -> tuple[list[FakeSocket], list[FakeSocket], list[FakeSocket]]:
        nonlocal select_calls
        select_calls += 1
        return (readable if select_calls == 1 else []), [], []

    monkeypatch.setattr(discovery_module, "_local_ipv4_addresses", lambda: addresses)
    monkeypatch.setattr(discovery_module.socket, "socket", socket_factory)
    monkeypatch.setattr(discovery_module.select, "select", fake_select)

    locations = discovery_module._ssdp_locations(0.1)

    assert locations == {"http://speaker/device.xml"}
    assert [sock.address for sock in sockets] == list(addresses)
    assert all(sock.closed for sock in sockets)
