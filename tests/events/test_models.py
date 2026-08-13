import pytest

import sonosify.events.models as events_models
from sonosify.events import (
    ALL_SERVICES,
    AlarmClockEvent,
    AVTransportEvent,
    EventService,
    PlayMode,
    RenderingControlEvent,
    TransportState,
    UnknownSonosEvent,
    ZoneGroupTopologyEvent,
)
from sonosify.events.models import (
    event_path,
    event_type,
    normalize_service,
    require_service,
)


def test_av_transport_event_parses_aliases_and_coerces() -> None:
    event = AVTransportEvent.model_validate(
        {
            "TransportState": "PLAYING",
            "CurrentPlayMode": "SHUFFLE",
            "CurrentCrossfadeMode": "1",
            "CurrentTrack": "3",
            "NumberOfTracks": "12",
            "CurrentTransportActions": "Play, Pause, Next",
        }
    )

    assert event.transport_state is TransportState.PLAYING
    assert event.play_mode is PlayMode.SHUFFLE
    assert event.crossfade is True
    assert event.current_track == 3
    assert event.number_of_tracks == 12
    assert event.transport_actions == ("Play", "Pause", "Next")


def test_event_alias_generator_preserves_upnp_initialisms() -> None:
    event = ZoneGroupTopologyEvent.model_validate(
        {
            "ZoneGroupID": "group-id",
            "ZonePlayerUUIDsInGroup": "player-1, player-2",
            "AreasUpdateID": "update-id",
        }
    )

    assert event.zone_group_id == "group-id"
    assert event.zone_player_uuids_in_group == ("player-1", "player-2")
    assert event.areas_update_id == "update-id"

    serialized = event.model_dump(by_alias=True)
    assert serialized["service"] is EventService.ZONE_GROUP_TOPOLOGY
    assert serialized["ZoneGroupID"] == "group-id"
    assert "Service" not in serialized


def test_av_transport_event_is_lenient_on_garbage() -> None:
    event = AVTransportEvent.model_validate(
        {"TransportState": "BOGUS", "CurrentPlayMode": "BOGUS", "CurrentTrack": "n/a"}
    )

    assert event.transport_state is None
    assert event.play_mode is None
    assert event.current_track is None


def test_rendering_control_event_coerces_flags_and_signed_numbers() -> None:
    event = RenderingControlEvent.model_validate(
        {"Volume": "17", "Mute": "1", "Bass": "-5", "Loudness": "0", "NightMode": "x"}
    )

    assert event.volume == 17
    assert event.muted is True
    assert event.bass == -5
    assert event.loudness is False
    assert event.night_mode is None


def test_flag_csv_and_enum_coercers_pass_through_non_string_values() -> None:
    # These BeforeValidators only parse raw SOAP string payloads; pydantic
    # itself may pass through an already-correct type (e.g. a default), which
    # must be returned untouched rather than mis-parsed as a string.
    assert events_models._flag(True) is True
    assert events_models._csv(("a", "b")) == ("a", "b")

    coerce_state = events_models._enum_or_none(TransportState).func
    assert coerce_state(None) is None


def test_events_keep_undeclared_variables_in_values() -> None:
    values = {"Volume": "17", "SomeFutureVariable": "42"}

    event = RenderingControlEvent.model_validate({**values, "values": values})

    assert event.values == values


def test_alarm_clock_event_defaults_service() -> None:
    assert AlarmClockEvent().service is EventService.ALARM_CLOCK


def test_normalize_service_accepts_punctuation_and_camel_case() -> None:
    assert normalize_service("AVTransport") is EventService.AV_TRANSPORT
    assert normalize_service("av_transport") is EventService.AV_TRANSPORT
    assert normalize_service("rendering-control") is EventService.RENDERING_CONTROL
    assert normalize_service(EventService.QUEUE) is EventService.QUEUE


def test_normalize_service_returns_none_for_unknown_service() -> None:
    assert normalize_service("nonexistent") is None


def test_require_service_rejects_unknown_service() -> None:
    with pytest.raises(ValueError, match="unsupported event service"):
        require_service("nonexistent")


def test_event_type_falls_back_to_unknown_event() -> None:
    assert event_type("nonexistent") is UnknownSonosEvent
    assert event_type("ZoneGroupTopology").event_path == "/ZoneGroupTopology/Event"


@pytest.mark.parametrize("service", ALL_SERVICES)
def test_every_service_maps_to_a_distinct_typed_event(service: EventService) -> None:
    model = event_type(service)

    assert model is not UnknownSonosEvent
    assert model().service is service
    assert event_path(service).endswith("/Event")


def test_all_services_have_unique_event_paths() -> None:
    paths = [event_path(service) for service in ALL_SERVICES]

    assert len(set(paths)) == len(paths)
