from sonosify.discovery import _parse_topology, _speaker_from_device_xml
from sonosify.models import Speaker


def test_speaker_from_device_xml_reads_room_and_uid() -> None:
    xml = (
        '<root xmlns="urn:schemas-upnp-org:device-1-0">'
        "<device>"
        "<roomName>Kitchen</roomName>"
        "<UDN>uuid:RINCON_123</UDN>"
        "</device>"
        "</root>"
    )

    speaker = _speaker_from_device_xml("http://192.168.1.10:1400/xml/device.xml", xml)

    assert speaker == Speaker(ip="192.168.1.10", port=1400, room_name="Kitchen", uid="RINCON_123")


def test_parse_topology_builds_speakers_and_group() -> None:
    state = (
        "<ZoneGroupState><ZoneGroups>"
        '<ZoneGroup Coordinator="RINCON_A" ID="RINCON_A:1">'
        '<ZoneGroupMember UUID="RINCON_A" '
        'Location="http://192.168.1.10:1400/xml/device.xml" ZoneName="Kitchen"/>'
        '<ZoneGroupMember UUID="RINCON_B" '
        'Location="http://192.168.1.11:1400/xml/device.xml" ZoneName="Office"/>'
        "</ZoneGroup>"
        "</ZoneGroups></ZoneGroupState>"
    )

    parsed = _parse_topology(state, known={})
    assert parsed is not None
    speakers, groups = parsed

    assert {s.room_name for s in speakers} == {"Kitchen", "Office"}
    assert len(groups) == 1
    group = groups[0]
    assert group.coordinator_uid == "RINCON_A"
    assert group.coordinator is not None
    assert group.coordinator.room_name == "Kitchen"


def test_parse_topology_returns_none_for_empty_state() -> None:
    assert _parse_topology("", known={}) is None
