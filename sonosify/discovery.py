import asyncio
import socket
from collections.abc import Iterable
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from sonosify._parsing import local_name, parse_headers
from sonosify.client import DEFAULT_TIMEOUT, SonosClient
from sonosify.errors import DiscoveryError
from sonosify.models import Group, Speaker
from sonosify.topology import SonosSystem

DEFAULT_DISCOVERY_TIMEOUT = 2.0

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


async def discover(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
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

    return SonosSystem(speakers=speakers, groups=groups, timeout=timeout)


def _ssdp_locations(timeout: float) -> set[str]:
    # Blocking UDP multicast, run in a thread via asyncio.to_thread. asyncio's
    # create_datagram_endpoint is not a reliable substitute here: on Windows it
    # sends the M-SEARCH out the wrong interface and receives no replies.
    locations: set[str] = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.settimeout(timeout)
        sock.sendto(_SSDP_SEARCH_MESSAGE, _SSDP_ADDRESS)
        while True:
            try:
                data, _ = sock.recvfrom(65535)
            except TimeoutError:
                break
            _, headers = parse_headers(data.decode(errors="ignore"))
            location = headers.get("location")
            if location:
                locations.add(location)
    return locations


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
    device = _first(root, "device")
    if device is None:
        device = root
    room = _text(device, "roomName") or _text(device, "friendlyName")
    uid = _text(device, "UDN").removeprefix("uuid:")
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
        if local_name(zone_group.tag) != "ZoneGroup":
            continue
        group_id = zone_group.attrib.get("ID", "")
        coordinator_uid = zone_group.attrib.get("Coordinator", "")
        members: list[Speaker] = []
        for member in list(zone_group):
            if local_name(member.tag) != "ZoneGroupMember":
                continue
            uid = member.attrib.get("UUID", "")
            location = member.attrib.get("Location", "")
            parsed = urlparse(location)
            base = known.get(uid)
            speaker = Speaker(
                ip=parsed.hostname or (base.ip if base else ""),
                port=parsed.port or (base.port if base else 1400),
                room_name=member.attrib.get("ZoneName", "")
                or (base.room_name if base else ""),
                uid=uid,
                zone_name=member.attrib.get("ZoneName", ""),
                coordinator_uid=coordinator_uid,
                is_coordinator=uid == coordinator_uid,
                invisible=member.attrib.get("Invisible", "0") == "1",
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
