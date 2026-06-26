from sonosify import parse_track_id, track_metadata


def test_parse_track_id_from_bare_id() -> None:
    track = parse_track_id("abc123")

    assert track.id == "abc123"
    assert track.uri == "spotify:track:abc123"
    assert track.sonos_uri.startswith("x-sonos-spotify:")


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
