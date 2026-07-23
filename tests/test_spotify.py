import pytest

from sonosify import parse_track_id, track_metadata


def test_parse_track_id_from_bare_id() -> None:
    track = parse_track_id("abc123")

    assert track.id == "abc123"
    assert track.uri == "spotify:track:abc123"
    assert track.sonos_uri == "x-sonos-spotify:spotify:track:abc123?sid=9&flags=0&sn=2"


def test_parse_track_id_from_canonical_uri() -> None:
    track = parse_track_id("spotify:track:abc123")

    assert track.id == "abc123"


def test_parse_track_id_from_share_url() -> None:
    track = parse_track_id("https://open.spotify.com/track/xyz?si=ignored")

    assert track.uri == "spotify:track:xyz"


def test_track_metadata_contains_sonos_service_token() -> None:
    track = parse_track_id("abc123")

    metadata = track_metadata(track, "Focus")

    assert "Focus" in metadata
    assert "SA_RINCON2311_X_#Svc2311-0-Token" in metadata


def test_track_metadata_falls_back_to_track_uri_when_no_title() -> None:
    track = parse_track_id("abc123")

    metadata = track_metadata(track)

    assert "spotify:track:abc123" in metadata


def test_parse_track_id_from_uri_query_param() -> None:
    track = parse_track_id(
        "https://open.spotify.com/embed?uri=spotify%3Atrack%3Aabc123"
    )

    assert track.id == "abc123"


def test_parse_track_id_rejects_malformed_spotify_uri() -> None:
    with pytest.raises(ValueError, match="expected track URI"):
        parse_track_id("spotify:album:abc123")


def test_parse_track_id_rejects_unsupported_value() -> None:
    with pytest.raises(ValueError, match="unsupported track id or URI"):
        parse_track_id("not a track/id")
