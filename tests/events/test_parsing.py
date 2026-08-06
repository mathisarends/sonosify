from html import escape

from sonosify.events import (
    AVTransportEvent,
    DevicePropertiesEvent,
    EventService,
    QueueEvent,
    RenderingControlEvent,
    TransportState,
    UnknownSonosEvent,
    VirtualLineInEvent,
    parse_notify_event,
)
from sonosify.events.parsing import parse_last_change


def _propertyset(*properties: str) -> str:
    body = "".join(f"<e:property>{property}</e:property>" for property in properties)
    return f'<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">{body}</e:propertyset>'


def _last_change(
    inner: str, *, namespace: str = "AVT", container: str = "InstanceID"
) -> str:
    raw = (
        f'<Event xmlns="urn:schemas-upnp-org:metadata-1-0/{namespace}/">'
        f'<{container} val="0">{inner}</{container}>'
        "</Event>"
    )
    return f"<LastChange>{escape(raw)}</LastChange>"


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


def test_parse_notify_event_types_properties_sent_outside_last_change() -> None:
    body = _propertyset("<ZoneName>Kitchen</ZoneName>", "<MicEnabled>1</MicEnabled>")

    event = parse_notify_event(body, service="device_properties")

    assert isinstance(event, DevicePropertiesEvent)
    assert event.zone_name == "Kitchen"
    assert event.mic_enabled is True


def test_parse_notify_event_preserves_unknown_service_as_raw_event() -> None:
    body = _propertyset("<ZoneName>Kitchen</ZoneName>")

    event = parse_notify_event(body, service="nonexistent")

    assert isinstance(event, UnknownSonosEvent)
    assert event.service == "nonexistent"
    assert event.values == {"ZoneName": "Kitchen"}


def test_parse_notify_event_keeps_master_channel_over_stereo_pair_channels() -> None:
    body = _propertyset(
        _last_change(
            '<Volume channel="Master" val="17"/>'
            '<Volume channel="LF" val="100"/>'
            '<Volume channel="RF" val="100"/>',
            namespace="RCS",
        )
    )

    event = parse_notify_event(body, service=EventService.RENDERING_CONTROL)

    assert isinstance(event, RenderingControlEvent)
    assert event.volume == 17
    assert event.values["Volume:LF"] == "100"


def test_parse_notify_event_reads_queue_last_change_container() -> None:
    body = _propertyset(
        _last_change('<UpdateID val="7"/><Curated val="0"/>', container="QueueID")
    )

    event = parse_notify_event(body, service="Queue")

    assert isinstance(event, QueueEvent)
    assert event.update_id == 7
    assert event.curated is False


def test_parse_notify_event_separates_current_next_and_enqueued_tracks() -> None:
    body = _propertyset(
        _last_change(
            f'<CurrentTrackMetaData val="{escape(_didl("Now"), quote=True)}"/>'
            f'<NextTrackMetaData val="{escape(_didl("Later"), quote=True)}"/>'
            f'<EnqueuedTransportURIMetaData val="{escape(_didl("Station"), quote=True)}"/>'
        )
    )

    event = parse_notify_event(body, service="av_transport")

    assert isinstance(event, AVTransportEvent)
    assert event.track is not None and event.track.title == "Now"
    assert event.next_track is not None and event.next_track.title == "Later"
    assert event.enqueued_track is not None and event.enqueued_track.title == "Station"


def test_parse_notify_event_composes_the_virtual_line_in_track() -> None:
    body = _propertyset(
        _last_change(
            f'<CurrentTrackMetaData val="{escape(_didl("Airplay"), quote=True)}"/>'
            '<CurrentTrackURI val="x-sonos-vli:RINCON_1:2"/>'
        )
    )

    event = parse_notify_event(body, service="virtual_line_in")

    assert isinstance(event, VirtualLineInEvent)
    assert event.track is not None
    assert event.track.title == "Airplay"
    assert event.track.uri == "x-sonos-vli:RINCON_1:2"


def test_events_without_track_sources_do_not_grow_a_track_field() -> None:
    body = _propertyset(
        _last_change('<Volume channel="Master" val="1"/>', namespace="RCS")
    )

    event = parse_notify_event(body, service="rendering_control")

    assert not hasattr(event, "track")


def _didl(title: str) -> str:
    return (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        f"<item><dc:title>{title}</dc:title></item></DIDL-Lite>"
    )


def test_parse_notify_event_handles_multiple_properties() -> None:
    body = (
        '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
        "<e:property><ZoneName>Kitchen</ZoneName></e:property>"
        "<e:property><Icon>x.png</Icon></e:property>"
        "</e:propertyset>"
    )

    event = parse_notify_event(body, service="device_properties")

    assert event.values == {"ZoneName": "Kitchen", "Icon": "x.png"}
