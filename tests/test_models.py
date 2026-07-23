import pytest
from pydantic import ValidationError

from sonosify.models import Favorite, Group, PlaybackState, Speaker, Track


def test_speaker_defaults() -> None:
    speaker = Speaker(ip="192.168.1.10", room_name="Kitchen")

    assert speaker.uid == ""
    assert speaker.port == 1400
    assert speaker.is_coordinator is False
    assert speaker.invisible is False


def test_models_are_frozen() -> None:
    speaker = Speaker(ip="1.2.3.4", room_name="Office")
    with pytest.raises(ValidationError):
        speaker.room_name = "Kitchen"  # type: ignore[misc]


def test_group_coordinator_returns_matching_member() -> None:
    coordinator = Speaker(ip="1", room_name="Kitchen", uid="k", is_coordinator=True)
    member = Speaker(ip="2", room_name="Office", uid="o")
    group = Group(id="g", coordinator_uid="k", members=(coordinator, member))

    assert group.coordinator == coordinator


def test_group_coordinator_returns_none_when_absent() -> None:
    member = Speaker(ip="2", room_name="Office", uid="o")
    group = Group(id="g", coordinator_uid="k", members=(member,))

    assert group.coordinator is None


def test_track_and_playback_state_defaults() -> None:
    track = Track(title="Song")
    assert track.position is None
    assert track.duration == ""

    state = PlaybackState(state="PLAYING", track=track)
    assert state.relative_time == ""
    assert state.track == track


def test_favorite_requires_title_and_uri() -> None:
    favorite = Favorite(title="Jazz", uri="x-rincon:1")
    assert favorite.metadata == ""
    assert favorite.album_art_uri == ""

    with pytest.raises(ValidationError):
        Favorite(uri="x-rincon:1")  # type: ignore[call-arg]
