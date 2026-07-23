from html import escape

from sonosify.events import (
    AVTransportEvent,
    EventService,
    RenderingControlEvent,
    TransportState,
    UnknownSonosEvent,
    parse_notify_event,
)
from sonosify.events.parsing import parse_last_change


def test_parse_last_change_transport_state_and_metadata() -> None:
    didl = (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        "<item><dc:title>Song</dc:title><dc:creator>Artist</dc:creator></item>"
        "</DIDL-Lite>"
    )
    raw = (
        '<Event xmlns="urn:schemas-upnp-org:metadata-1-0/AVT/">'
        '<InstanceID val="0">'
        '<TransportState val="PLAYING"/>'
        '<CurrentTrack val="2"/>'
        f'<CurrentTrackMetaData val="{escape(didl, quote=True)}"/>'
        "</InstanceID>"
        "</Event>"
    )

    values = parse_last_change(raw)

    assert values["TransportState"] == "PLAYING"
    assert values["CurrentTrack"] == "2"
    assert "Song" in values["CurrentTrackMetaData"]


def test_parse_last_change_returns_empty_for_empty_input() -> None:
    assert parse_last_change("") == {}


def test_parse_last_change_ignores_event_and_instance_id_tags() -> None:
    raw = (
        '<Event xmlns="urn:schemas-upnp-org:metadata-1-0/AVT/">'
        '<InstanceID val="0"><Volume val="17"/></InstanceID>'
        "</Event>"
    )

    values = parse_last_change(raw)

    assert values == {"Volume": "17"}


def test_parse_notify_event_returns_typed_av_transport_event() -> None:
    last_change = (
        '<Event xmlns="urn:schemas-upnp-org:metadata-1-0/AVT/">'
        '<InstanceID val="0"><TransportState val="PLAYING"/></InstanceID>'
        "</Event>"
    )
    body = (
        '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
        f"<e:property><LastChange>{escape(last_change)}</LastChange></e:property>"
        "</e:propertyset>"
    )

    event = parse_notify_event(body, service="av_transport")

    assert isinstance(event, AVTransportEvent)
    assert event.service is EventService.AV_TRANSPORT
    assert event.transport_state is TransportState.PLAYING


def test_parse_notify_event_extracts_track_from_current_track_metadata() -> None:
    didl = (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        "<item><dc:title>Song</dc:title></item></DIDL-Lite>"
    )
    last_change = (
        '<Event xmlns="urn:schemas-upnp-org:metadata-1-0/AVT/">'
        '<InstanceID val="0">'
        '<TransportState val="PLAYING"/>'
        '<CurrentTrackURI val="x-sonos:1"/>'
        f'<CurrentTrackMetaData val="{escape(didl, quote=True)}"/>'
        "</InstanceID>"
        "</Event>"
    )
    body = (
        '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
        f"<e:property><LastChange>{escape(last_change)}</LastChange></e:property>"
        "</e:propertyset>"
    )

    event = parse_notify_event(body, service="av_transport")

    assert isinstance(event, AVTransportEvent)
    assert event.track is not None
    assert event.track.title == "Song"
    assert event.track.uri == "x-sonos:1"


def test_parse_notify_event_normalizes_rendering_control() -> None:
    last_change = (
        '<Event xmlns="urn:schemas-upnp-org:metadata-1-0/RCS/">'
        '<InstanceID val="0"><Volume channel="Master" val="17"/><Mute channel="Master" val="0"/></InstanceID>'
        "</Event>"
    )
    body = (
        '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
        f"<e:property><LastChange>{escape(last_change)}</LastChange></e:property>"
        "</e:propertyset>"
    )

    event = parse_notify_event(
        body, service="rendering_control", sid="uuid:test", sequence=1
    )

    assert isinstance(event, RenderingControlEvent)
    assert event.service is EventService.RENDERING_CONTROL
    assert event.sid == "uuid:test"
    assert event.sequence == 1
    assert event.volume == 17
    assert event.muted is False


def test_parse_notify_event_preserves_unknown_service_as_raw_event() -> None:
    body = (
        '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
        "<e:property><ZoneName>Kitchen</ZoneName></e:property>"
        "</e:propertyset>"
    )

    event = parse_notify_event(body, service="device_properties")

    assert isinstance(event, UnknownSonosEvent)
    assert event.service == "device_properties"
    assert event.values == {"ZoneName": "Kitchen"}


def test_parse_notify_event_handles_multiple_properties() -> None:
    body = (
        '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
        "<e:property><ZoneName>Kitchen</ZoneName></e:property>"
        "<e:property><Icon>x.png</Icon></e:property>"
        "</e:propertyset>"
    )

    event = parse_notify_event(body, service="device_properties")

    assert event.values == {"ZoneName": "Kitchen", "Icon": "x.png"}
