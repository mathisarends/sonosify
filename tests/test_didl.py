from sonosify.didl import (
    parse_favorites,
    parse_track_metadata,
    radio_metadata,
    radio_uri,
)
from sonosify.models import Favorite, Track


def test_parse_track_metadata_reads_didl_fields() -> None:
    didl = (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        "<item><dc:title>Song</dc:title><dc:creator>Artist</dc:creator>"
        "<upnp:album>Album</upnp:album>"
        "<res>x-sonos:track</res><upnp:albumArtURI>http://art</upnp:albumArtURI>"
        "</item></DIDL-Lite>"
    )

    track = parse_track_metadata(didl, duration="0:03:00", position=2)

    assert track == Track(
        title="Song",
        creator="Artist",
        album="Album",
        uri="x-sonos:track",
        album_art_uri="http://art",
        duration="0:03:00",
        position=2,
    )


def test_parse_track_metadata_prefers_explicit_uri_over_res() -> None:
    didl = (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        "<item><res>from-didl</res></item></DIDL-Lite>"
    )

    track = parse_track_metadata(didl, uri="explicit-uri")

    assert track.uri == "explicit-uri"


def test_parse_track_metadata_returns_bare_track_for_empty_or_invalid_input() -> None:
    assert parse_track_metadata("", uri="x", duration="1:00", position=1) == Track(
        uri="x", duration="1:00", position=1
    )
    assert parse_track_metadata("<not valid xml", uri="x") == Track(uri="x")


def test_parse_track_metadata_falls_back_to_root_without_item_element() -> None:
    didl = (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        "<dc:title>Direct</dc:title><res>x-sonos:direct</res></DIDL-Lite>"
    )

    track = parse_track_metadata(didl)

    assert track.title == "Direct"
    assert track.uri == "x-sonos:direct"


def test_radio_uri_rewrites_http_and_https_schemes() -> None:
    assert (
        radio_uri("http://stream.example/radio")
        == "x-rincon-mp3radio://stream.example/radio"
    )
    assert (
        radio_uri("https://stream.example/radio")
        == "x-rincon-mp3radio://stream.example/radio"
    )


def test_radio_uri_leaves_non_http_schemes_untouched() -> None:
    assert radio_uri("x-sonosapi-stream:station") == "x-sonosapi-stream:station"


def test_parse_favorites_collects_items_and_containers() -> None:
    xml = (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        "<item><dc:title>Jazz FM</dc:title><res>x-rincon:1</res></item>"
        "<container><dc:title>My Playlist</dc:title><res>x-file:2</res></container>"
        "</DIDL-Lite>"
    )

    favorites = parse_favorites(xml)

    assert favorites == [
        Favorite(title="Jazz FM", uri="x-rincon:1", metadata=favorites[0].metadata),
        Favorite(title="My Playlist", uri="x-file:2", metadata=favorites[1].metadata),
    ]
    assert "container" in favorites[1].metadata
    assert "My Playlist" in favorites[1].metadata


def test_parse_favorites_returns_empty_for_empty_or_invalid_input() -> None:
    assert parse_favorites("") == []
    assert parse_favorites("<not valid xml") == []


def test_radio_metadata_escapes_title_and_uri() -> None:
    metadata = radio_metadata("Rock & Roll", "http://stream?a=1&b=2")

    assert "Rock &amp; Roll" in metadata
    assert "http://stream?a=1&amp;b=2" in metadata
    assert "audioBroadcast" in metadata
