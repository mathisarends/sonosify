from html import escape

from sonosify.events import (
    AVTransportEvent,
    AVTransportValues,
    EventService,
    RenderingControlEvent,
    RenderingControlValues,
    TransportState,
    UnknownSonosEvent,
    parse_last_change,
    parse_notify_event,
)


def test_av_transport_values_parse_aliases_and_coerce() -> None:
    values = AVTransportValues.model_validate(
        {
            "TransportState": "PLAYING",
            "CurrentTrack": "3",
            "CurrentTrackURI": "x-sonos:1",
        }
    )

    assert values.transport_state is TransportState.PLAYING
    assert values.current_track == 3
    assert values.current_track_uri == "x-sonos:1"


def test_av_transport_values_lenient_on_garbage() -> None:
    values = AVTransportValues.model_validate(
        {"TransportState": "BOGUS", "CurrentTrack": "n/a"}
    )

    assert values.transport_state is None
    assert values.current_track is None


def test_rendering_control_values_coerce_volume_and_mute() -> None:
    values = RenderingControlValues.model_validate({"Volume": "17", "Mute": "1"})

    assert values.volume == 17
    assert values.muted is True
    assert RenderingControlValues.model_validate({"Mute": "x"}).muted is None


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
