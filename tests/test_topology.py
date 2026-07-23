import pytest

from sonosify.client import SonosClient
from sonosify.errors import AmbiguousSpeakerError, SpeakerNotFoundError
from sonosify.models import Group, Speaker
from sonosify.topology import SonosSystem


def test_system_finds_exact_and_fuzzy_room() -> None:
    kitchen = Speaker(
        ip="192.168.1.10",
        room_name="Kitchen",
        uid="k",
        coordinator_uid="k",
        is_coordinator=True,
    )
    office = Speaker(
        ip="192.168.1.11", room_name="Office", uid="o", coordinator_uid="k"
    )
    system = SonosSystem(
        (kitchen, office),
        (Group(id="g", coordinator_uid="k", members=(kitchen, office)),),
    )

    assert system.find("Kitchen") == kitchen
    assert system.find("off") == office
    assert system.coordinator_for(office) == kitchen
    with pytest.raises(AttributeError):
        system.speakers = ()  # type: ignore[misc]


def test_system_reports_ambiguous_fuzzy_room() -> None:
    system = SonosSystem(
        (
            Speaker(ip="1", room_name="Office"),
            Speaker(ip="2", room_name="Offsite"),
        ),
        (),
    )

    try:
        system.find("off")
    except AmbiguousSpeakerError as exc:
        assert exc.matches == ("Office", "Offsite")
        with pytest.raises(AttributeError):
            exc.matches = ()  # type: ignore[misc]
    else:
        raise AssertionError("expected AmbiguousSpeakerError")


def test_system_find_by_ip() -> None:
    kitchen = Speaker(ip="192.168.1.10", room_name="Kitchen")
    system = SonosSystem((kitchen,), ())

    assert system.find(ip="192.168.1.10") == kitchen
    with pytest.raises(SpeakerNotFoundError):
        system.find(ip="10.0.0.1")


def test_system_find_without_query_requires_single_speaker() -> None:
    single = SonosSystem((Speaker(ip="1", room_name="Kitchen"),), ())
    assert single.find() == single.speakers[0]

    multiple = SonosSystem(
        (Speaker(ip="1", room_name="Kitchen"), Speaker(ip="2", room_name="Office")),
        (),
    )
    with pytest.raises(SpeakerNotFoundError):
        multiple.find()


def test_system_find_raises_when_no_match() -> None:
    system = SonosSystem((Speaker(ip="1", room_name="Kitchen"),), ())

    with pytest.raises(SpeakerNotFoundError):
        system.find("Bathroom")


def test_system_find_excludes_invisible_speakers_by_default() -> None:
    hidden = Speaker(ip="1", room_name="Boost", invisible=True)
    system = SonosSystem((hidden,), ())

    with pytest.raises(SpeakerNotFoundError):
        system.find("Boost")
    assert system.find("Boost", include_invisible=True) == hidden


def test_system_coordinator_for_falls_back_to_self_when_unknown() -> None:
    orphan = Speaker(ip="1", room_name="Attic", uid="a", coordinator_uid="missing")
    system = SonosSystem((orphan,), ())

    assert system.coordinator_for(orphan) == orphan


def test_system_client_resolves_to_coordinator_by_default() -> None:
    coordinator = Speaker(
        ip="192.168.1.10", room_name="Kitchen", uid="k", is_coordinator=True
    )
    member = Speaker(
        ip="192.168.1.11", room_name="Office", uid="o", coordinator_uid="k"
    )
    system = SonosSystem((coordinator, member), ())

    client = system.client("Office")

    assert isinstance(client, SonosClient)
    assert client.ip == "192.168.1.10"


def test_system_client_can_target_group_member_directly() -> None:
    coordinator = Speaker(
        ip="192.168.1.10", room_name="Kitchen", uid="k", is_coordinator=True
    )
    member = Speaker(
        ip="192.168.1.11", room_name="Office", uid="o", coordinator_uid="k"
    )
    system = SonosSystem((coordinator, member), ())

    client = system.client("Office", coordinator=False)

    assert client.ip == "192.168.1.11"
