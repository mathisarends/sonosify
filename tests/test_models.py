import sonosify
import sonosify.client as client_models
import sonosify.events as event_models
from sonosify.models import (
    Group,
    PlayMode,
    PositionInfo,
    RepeatMode,
    Speaker,
    TransportInfo,
    TransportState,
)


def test_group_coordinator_returns_matching_member() -> None:
    coordinator = Speaker(ip="1", room_name="Kitchen", uid="k", is_coordinator=True)
    member = Speaker(ip="2", room_name="Office", uid="o")
    group = Group(id="g", coordinator_uid="k", members=(coordinator, member))

    assert group.coordinator == coordinator


def test_group_coordinator_returns_none_when_absent() -> None:
    member = Speaker(ip="2", room_name="Office", uid="o")
    group = Group(id="g", coordinator_uid="k", members=(member,))

    assert group.coordinator is None


def test_shared_models_keep_public_and_legacy_imports_compatible() -> None:
    for model in (PlayMode, PositionInfo, RepeatMode, TransportInfo, TransportState):
        assert getattr(sonosify, model.__name__) is model
    assert client_models.PositionInfo is PositionInfo
    assert client_models.TransportInfo is TransportInfo
    assert event_models.PlayMode is PlayMode
    assert event_models.TransportState is TransportState
