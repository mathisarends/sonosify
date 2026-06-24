from sonosify.discovery import SonosSystem
from sonosify.errors import AmbiguousSpeakerError
from sonosify.models import Group, Speaker


def test_system_finds_exact_and_fuzzy_room() -> None:
    kitchen = Speaker(ip="192.168.1.10", room_name="Kitchen", uid="k", coordinator_uid="k", is_coordinator=True)
    office = Speaker(ip="192.168.1.11", room_name="Office", uid="o", coordinator_uid="k")
    system = SonosSystem(speakers=(kitchen, office), groups=(Group("g", "k", (kitchen, office)),))

    assert system.find("Kitchen") == kitchen
    assert system.find("off") == office
    assert system.coordinator_for(office) == kitchen


def test_system_reports_ambiguous_fuzzy_room() -> None:
    system = SonosSystem(
        speakers=(
            Speaker(ip="1", room_name="Office"),
            Speaker(ip="2", room_name="Offsite"),
        ),
        groups=(),
    )

    try:
        system.find("off")
    except AmbiguousSpeakerError as exc:
        assert exc.matches == ["Office", "Offsite"]
    else:
        raise AssertionError("expected AmbiguousSpeakerError")
