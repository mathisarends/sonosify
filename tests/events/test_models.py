from sonosify.events import EventService, TransportState
from sonosify.events.models import (
    AVTransportValues,
    RenderingControlValues,
    normalize_service,
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
    assert RenderingControlValues.model_validate({"Mute": "0"}).muted is False


def test_normalize_service_accepts_known_aliases() -> None:
    assert normalize_service("av") is EventService.AV_TRANSPORT
    assert normalize_service("AVTransport") is EventService.AV_TRANSPORT
    assert normalize_service("rendering-control") is EventService.RENDERING_CONTROL
    assert normalize_service(EventService.RENDERING_CONTROL) is (
        EventService.RENDERING_CONTROL
    )


def test_normalize_service_returns_none_for_unknown_service() -> None:
    assert normalize_service("device_properties") is None
