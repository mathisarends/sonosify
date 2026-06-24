from sonosify import parse_spotify_uri, spotify_metadata


def test_parse_spotify_uri_from_canonical_uri() -> None:
    item = parse_spotify_uri("spotify:track:abc123")

    assert item.kind == "track"
    assert item.id == "abc123"
    assert item.sonos_uri.startswith("x-sonos-spotify:")


def test_parse_spotify_uri_from_share_url() -> None:
    item = parse_spotify_uri("https://open.spotify.com/album/xyz?si=ignored")

    assert item.uri == "spotify:album:xyz"


def test_spotify_metadata_contains_sonos_service_token() -> None:
    item = parse_spotify_uri("spotify:playlist:list123")

    metadata = spotify_metadata(item, "Focus")

    assert "Focus" in metadata
    assert "SA_RINCON2311_X_#Svc2311-0-Token" in metadata
