import asyncio
import select
import socket
import time
from collections.abc import Iterable
from enum import StrEnum
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from sonosify._parsing import local_name, parse_headers
from sonosify.client import DEFAULT_TIMEOUT, SonosClient
from sonosify.errors import DiscoveryError
from sonosify.models import Group, Speaker
from sonosify.topology import SonosSystem

_DEFAULT_DISCOVERY_TIMEOUT = 2.0


async def discover(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    discovery_timeout: float = _DEFAULT_DISCOVERY_TIMEOUT,
    include_invisible: bool = False,
) -> SonosSystem:
    locations = await asyncio.to_thread(_ssdp_locations, discovery_timeout)
    if not locations:
        raise DiscoveryError("no Sonos speakers discovered via SSDP")

    speakers = await _speakers_from_locations(locations, timeout)
    if not speakers:
        raise DiscoveryError(
            "Sonos speakers responded but no device metadata could be parsed"
        )

    topology = await _topology_from_speakers(speakers, timeout)
    if topology:
        speakers, groups = topology
    else:
        groups = _groups_from_speakers(speakers)

    if not include_invisible:
        speakers = tuple(speaker for speaker in speakers if not speaker.invisible)
        groups = tuple(
            Group(
                id=group.id,
                coordinator_uid=group.coordinator_uid,
                members=tuple(s for s in group.members if not s.invisible),
            )
            for group in groups
            if any(not s.invisible for s in group.members)
        )

    return SonosSystem(speakers, groups, timeout)


_UUID_PREFIX = "uuid:"


class _DeviceTag(StrEnum):
    DEVICE = "device"
    ROOM_NAME = "roomName"
    FRIENDLY_NAME = "friendlyName"
    UDN = "UDN"


class _ZoneTag(StrEnum):
    GROUP = "ZoneGroup"
    MEMBER = "ZoneGroupMember"


class _ZoneAttr(StrEnum):
    ID = "ID"
    COORDINATOR = "Coordinator"
    UUID = "UUID"
    LOCATION = "Location"
    ZONE_NAME = "ZoneName"
    INVISIBLE = "Invisible"


_SSDP_ADDRESS = ("239.255.255.250", 1900)
_SONOS_ST = "urn:schemas-upnp-org:device:ZonePlayer:1"
_SSDP_SEARCH_MESSAGE = "\r\n".join(
    [
        "M-SEARCH * HTTP/1.1",
        f"HOST: {_SSDP_ADDRESS[0]}:{_SSDP_ADDRESS[1]}",
        'MAN: "ssdp:discover"',
        "MX: 1",
        f"ST: {_SONOS_ST}",
        "",
        "",
    ]
).encode()


def _ssdp_locations(timeout: float) -> set[str]:
    # Windows commonly prefers a virtual adapter for multicast. Send from every
    # local IPv4 address and use one deadline so extra adapters add no latency.
    locations: set[str] = set()
    sockets: list[socket.socket] = []
    try:
        for address in _local_ipv4_addresses() or ("0.0.0.0",):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            try:
                sock.bind((address, 0))
                if address != "0.0.0.0":
                    sock.setsockopt(
                        socket.IPPROTO_IP,
                        socket.IP_MULTICAST_IF,
                        socket.inet_aton(address),
                    )
                sock.setblocking(False)
                sock.sendto(_SSDP_SEARCH_MESSAGE, _SSDP_ADDRESS)
            except OSError:
                sock.close()
                continue
            sockets.append(sock)

        deadline = time.monotonic() + timeout
        while sockets and (remaining := deadline - time.monotonic()) > 0:
            readable, _, _ = select.select(sockets, [], [], remaining)
            if not readable:
                break
            for sock in readable:
                try:
                    data, _ = sock.recvfrom(65535)
                except BlockingIOError:
                    continue
                _, headers = parse_headers(data.decode(errors="ignore"))
                location = headers.get("location")
                if location:
                    locations.add(location)
    finally:
        for sock in sockets:
            sock.close()
    return locations


def _local_ipv4_addresses() -> tuple[str, ...]:
    try:
        candidates = socket.getaddrinfo(
            socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM
        )
    except OSError:
        return ()
    return tuple(
        dict.fromkeys(
            address[0] for *_, address in candidates if address[0] != "127.0.0.1"
        )
    )


async def _speakers_from_locations(
    locations: Iterable[str], timeout: float
) -> tuple[Speaker, ...]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [_speaker_from_location(client, location) for location in locations]
        results = await asyncio.gather(*tasks)
    speakers = {
        speaker.uid or speaker.ip: speaker for speaker in results if speaker is not None
    }
    return tuple(speakers.values())


async def _speaker_from_location(
    client: httpx.AsyncClient, location: str
) -> Speaker | None:
    try:
        response = await client.get(location)
        response.raise_for_status()
        return _speaker_from_device_xml(location, response.text)
    except (httpx.HTTPError, ElementTree.ParseError, ValueError):
        return None


def _speaker_from_device_xml(location: str, xml_text: str) -> Speaker:
    parsed = urlparse(location)
    root = ElementTree.fromstring(xml_text)
    device = _first(root, _DeviceTag.DEVICE)
    if device is None:
        device = root
    room = _text(device, _DeviceTag.ROOM_NAME) or _text(
        device, _DeviceTag.FRIENDLY_NAME
    )
    uid = _text(device, _DeviceTag.UDN).removeprefix(_UUID_PREFIX)
    return Speaker(
        ip=parsed.hostname or "", port=parsed.port or 1400, room_name=room, uid=uid
    )


async def _topology_from_speakers(
    speakers: tuple[Speaker, ...], timeout: float
) -> tuple[tuple[Speaker, ...], tuple[Group, ...]] | None:
    by_uid = {speaker.uid: speaker for speaker in speakers if speaker.uid}
    for speaker in speakers:
        try:
            async with SonosClient.from_speaker(speaker, timeout=timeout) as client:
                state = await client.get_zone_group_state()
        except Exception:
            continue
        parsed = _parse_topology(state, by_uid)
        if parsed is not None:
            return parsed
    return None


def _parse_topology(
    state: str, known: dict[str, Speaker]
) -> tuple[tuple[Speaker, ...], tuple[Group, ...]] | None:
    if not state:
        return None
    try:
        root = ElementTree.fromstring(state)
    except ElementTree.ParseError:
        return None

    speakers: dict[str, Speaker] = {}
    groups: list[Group] = []
    for zone_group in root.iter():
        if local_name(zone_group.tag) != _ZoneTag.GROUP:
            continue
        group_id = zone_group.attrib.get(_ZoneAttr.ID, "")
        coordinator_uid = zone_group.attrib.get(_ZoneAttr.COORDINATOR, "")
        members: list[Speaker] = []
        for member in list(zone_group):
            if local_name(member.tag) != _ZoneTag.MEMBER:
                continue
            uid = member.attrib.get(_ZoneAttr.UUID, "")
            location = member.attrib.get(_ZoneAttr.LOCATION, "")
            parsed = urlparse(location)
            base = known.get(uid)
            zone_name = member.attrib.get(_ZoneAttr.ZONE_NAME, "")
            speaker = Speaker(
                ip=parsed.hostname or (base.ip if base else ""),
                port=parsed.port or (base.port if base else 1400),
                room_name=zone_name or (base.room_name if base else ""),
                uid=uid,
                zone_name=zone_name,
                coordinator_uid=coordinator_uid,
                is_coordinator=uid == coordinator_uid,
                invisible=member.attrib.get(_ZoneAttr.INVISIBLE, "0") == "1",
            )
            speakers[uid or speaker.ip] = speaker
            members.append(speaker)
        groups.append(
            Group(id=group_id, coordinator_uid=coordinator_uid, members=tuple(members))
        )
    return tuple(speakers.values()), tuple(groups)


def _groups_from_speakers(speakers: tuple[Speaker, ...]) -> tuple[Group, ...]:
    return tuple(
        Group(
            id=speaker.uid or speaker.ip,
            coordinator_uid=speaker.uid,
            members=(speaker,),
        )
        for speaker in speakers
    )


def _first(root: ElementTree.Element, name: str) -> ElementTree.Element | None:
    for element in root.iter():
        if local_name(element.tag) == name:
            return element
    return None


def _text(root: ElementTree.Element, name: str) -> str:
    element = _first(root, name)
    return "" if element is None or element.text is None else element.text.strip()
