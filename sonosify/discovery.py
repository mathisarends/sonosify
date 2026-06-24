import asyncio
import socket
from collections.abc import Iterable
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, ConfigDict

from sonosify.client import DEFAULT_TIMEOUT, SonosClient
from sonosify.errors import AmbiguousSpeakerError, DiscoveryError, SpeakerNotFoundError
from sonosify.models import Group, Speaker

_SSDP_ADDRESS = ("239.255.255.250", 1900)
_SONOS_ST = "urn:schemas-upnp-org:device:ZonePlayer:1"


class SonosSystem(BaseModel):
    model_config = ConfigDict(frozen=True)

    speakers: tuple[Speaker, ...]
    groups: tuple[Group, ...]
    timeout: float = DEFAULT_TIMEOUT

    def find(
        self,
        query: str | None = None,
        *,
        ip: str | None = None,
        include_invisible: bool = False,
    ) -> Speaker:
        candidates = (
            self.speakers
            if include_invisible
            else tuple(s for s in self.speakers if not s.invisible)
        )
        if ip is not None:
            for speaker in candidates:
                if speaker.ip == ip:
                    return speaker
            raise SpeakerNotFoundError(f"no speaker with IP {ip}")

        if not query:
            visible = [speaker for speaker in candidates if speaker.room_name]
            if len(visible) == 1:
                return visible[0]
            raise SpeakerNotFoundError("room name is required when multiple speakers are available")

        normalized = query.casefold()
        exact = [speaker for speaker in candidates if speaker.room_name.casefold() == normalized]
        if len(exact) == 1:
            return exact[0]

        fuzzy = [speaker for speaker in candidates if normalized in speaker.room_name.casefold()]
        if len(fuzzy) == 1:
            return fuzzy[0]
        if len(fuzzy) > 1:
            raise AmbiguousSpeakerError(query, [speaker.room_name for speaker in fuzzy])
        raise SpeakerNotFoundError(f"no speaker matching {query!r}")

    def coordinator_for(self, speaker: Speaker) -> Speaker:
        uid = speaker.coordinator_uid or speaker.uid
        for candidate in self.speakers:
            if candidate.uid == uid:
                return candidate
        return speaker

    def client(
        self,
        query: str | None = None,
        *,
        ip: str | None = None,
        coordinator: bool = True,
        include_invisible: bool = False,
    ) -> SonosClient:
        speaker = self.find(query, ip=ip, include_invisible=include_invisible)
        if coordinator:
            speaker = self.coordinator_for(speaker)
        return SonosClient.from_speaker(speaker, timeout=self.timeout)


class SonosController:
    def __init__(
        self, *, timeout: float = DEFAULT_TIMEOUT, include_invisible: bool = False
    ) -> None:
        self.timeout = timeout
        self.include_invisible = include_invisible
        self.system: SonosSystem | None = None

    async def discover(self) -> SonosSystem:
        self.system = await discover(timeout=self.timeout, include_invisible=self.include_invisible)
        return self.system

    async def client(
        self,
        room: str | None = None,
        *,
        ip: str | None = None,
        coordinator: bool = True,
    ) -> SonosClient:
        system = self.system or await self.discover()
        return system.client(
            room,
            ip=ip,
            coordinator=coordinator,
            include_invisible=self.include_invisible,
        )

    async def play(self, room: str | None = None, *, ip: str | None = None) -> None:
        async with await self.client(room, ip=ip) as client:
            await client.play()

    async def pause(self, room: str | None = None, *, ip: str | None = None) -> None:
        async with await self.client(room, ip=ip) as client:
            await client.pause()

    async def stop(self, room: str | None = None, *, ip: str | None = None) -> None:
        async with await self.client(room, ip=ip) as client:
            await client.stop()

    async def set_volume(
        self, volume: int, room: str | None = None, *, ip: str | None = None
    ) -> None:
        async with await self.client(room, ip=ip, coordinator=False) as client:
            await client.set_volume(volume)


async def discover(
    *, timeout: float = DEFAULT_TIMEOUT, include_invisible: bool = False
) -> SonosSystem:
    locations = await asyncio.to_thread(_ssdp_locations, timeout)
    if not locations:
        raise DiscoveryError("no Sonos speakers discovered via SSDP")

    speakers = await _speakers_from_locations(locations, timeout)
    if not speakers:
        raise DiscoveryError("Sonos speakers responded but no device metadata could be parsed")

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
    message = "\r\n".join(
        [
            "M-SEARCH * HTTP/1.1",
            "HOST: 239.255.255.250:1900",
            'MAN: "ssdp:discover"',
            "MX: 1",
            f"ST: {_SONOS_ST}",
            "",
            "",
        ]
    ).encode()
    locations: set[str] = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.settimeout(timeout)
        sock.sendto(message, _SSDP_ADDRESS)
        while True:
            try:
                data, _ = sock.recvfrom(65535)
            except TimeoutError:
                break
            headers = _parse_headers(data.decode(errors="ignore"))
            location = headers.get("location")
            if location:
                locations.add(location)
    return locations


async def _speakers_from_locations(locations: Iterable[str], timeout: float) -> tuple[Speaker, ...]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [_speaker_from_location(client, location) for location in locations]
        results = await asyncio.gather(*tasks)
    speakers = {speaker.uid or speaker.ip: speaker for speaker in results if speaker is not None}
    return tuple(speakers.values())


async def _speaker_from_location(client: httpx.AsyncClient, location: str) -> Speaker | None:
    try:
        response = await client.get(location)
        response.raise_for_status()
        return _speaker_from_device_xml(location, response.text)
    except httpx.HTTPError, ElementTree.ParseError, ValueError:
        return None


def _speaker_from_device_xml(location: str, xml_text: str) -> Speaker:
    parsed = urlparse(location)
    root = ElementTree.fromstring(xml_text)
    device = _first(root, "device")
    if device is None:
        device = root
    room = _text(device, "roomName") or _text(device, "friendlyName")
    uid = _text(device, "UDN").removeprefix("uuid:")
    return Speaker(ip=parsed.hostname or "", port=parsed.port or 1400, room_name=room, uid=uid)


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
        if _local_name(zone_group.tag) != "ZoneGroup":
            continue
        group_id = zone_group.attrib.get("ID", "")
        coordinator_uid = zone_group.attrib.get("Coordinator", "")
        members: list[Speaker] = []
        for member in list(zone_group):
            if _local_name(member.tag) != "ZoneGroupMember":
                continue
            uid = member.attrib.get("UUID", "")
            location = member.attrib.get("Location", "")
            parsed = urlparse(location)
            base = known.get(uid)
            speaker = Speaker(
                ip=parsed.hostname or (base.ip if base else ""),
                port=parsed.port or (base.port if base else 1400),
                room_name=member.attrib.get("ZoneName", "") or (base.room_name if base else ""),
                uid=uid,
                zone_name=member.attrib.get("ZoneName", ""),
                coordinator_uid=coordinator_uid,
                is_coordinator=uid == coordinator_uid,
                invisible=member.attrib.get("Invisible", "0") == "1",
            )
            speakers[uid or speaker.ip] = speaker
            members.append(speaker)
        groups.append(Group(id=group_id, coordinator_uid=coordinator_uid, members=tuple(members)))
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


def _parse_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in raw.splitlines()[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().casefold()] = value.strip()
    return headers


def _first(root: ElementTree.Element, local_name: str) -> ElementTree.Element | None:
    for element in root.iter():
        if _local_name(element.tag) == local_name:
            return element
    return None


def _text(root: ElementTree.Element, local_name: str) -> str:
    element = _first(root, local_name)
    return "" if element is None or element.text is None else element.text.strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
