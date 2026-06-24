from html import escape
from urllib.parse import parse_qs, quote, urlparse

from pydantic import BaseModel, ConfigDict


class SpotifyItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    id: str

    @property
    def uri(self) -> str:
        return f"spotify:{self.kind}:{self.id}"

    @property
    def sonos_uri(self) -> str:
        encoded = quote(f"{self.kind}:{self.id}", safe="")
        return f"x-sonos-spotify:{encoded}?sid=12&flags=8224&sn=1"


def parse_spotify_uri(value: str) -> SpotifyItem:
    value = value.strip()
    if value.startswith("spotify:"):
        parts = value.split(":")
        if len(parts) >= 3 and parts[1] and parts[2]:
            return SpotifyItem(kind=parts[1], id=parts[2])
        raise ValueError(f"invalid Spotify URI: {value!r}")

    parsed = urlparse(value)
    if parsed.netloc.endswith("spotify.com"):
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 2:
            return SpotifyItem(kind=path_parts[0], id=path_parts[1])
        query = parse_qs(parsed.query)
        if "uri" in query:
            return parse_spotify_uri(query["uri"][0])

    raise ValueError(f"unsupported Spotify value: {value!r}")


def spotify_metadata(item: SpotifyItem, title: str = "") -> str:
    safe_title = escape(title or item.uri, quote=False)
    escaped_uri = escape(item.sonos_uri, quote=False)
    return (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        '<item id="100c206cspotify%3a" parentID="100c206cspotify%3a" restricted="true">'
        f"<dc:title>{safe_title}</dc:title>"
        "<upnp:class>object.item.audioItem.musicTrack</upnp:class>"
        '<desc id="cdudn" nameSpace="urn:schemas-rinconnetworks-com:metadata-1-0/">'
        "SA_RINCON2311_X_#Svc2311-0-Token"
        "</desc>"
        f'<res protocolInfo="sonos.com-spotify:*:audio/x-spotify:*">{escaped_uri}</res>'
        "</item>"
        "</DIDL-Lite>"
    )
