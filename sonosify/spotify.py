from html import escape
from urllib.parse import parse_qs, quote, urlparse

from pydantic import BaseModel, ConfigDict


class TrackReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str

    @property
    def uri(self) -> str:
        return f"spotify:track:{self.id}"

    @property
    def sonos_uri(self) -> str:
        encoded = quote(f"track:{self.id}", safe="")
        return f"x-sonos-spotify:{encoded}?sid=12&flags=8224&sn=1"


def parse_track_id(value: str) -> TrackReference:
    value = value.strip()
    if value.startswith("spotify:"):
        parts = value.split(":")
        if len(parts) >= 3 and parts[1] == "track" and parts[2]:
            return TrackReference(id=parts[2])
        raise ValueError(f"expected track URI, got: {value!r}")

    parsed = urlparse(value)
    if parsed.netloc.endswith("spotify.com"):
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[0] == "track":
            return TrackReference(id=path_parts[1])
        query = parse_qs(parsed.query)
        if "uri" in query:
            return parse_track_id(query["uri"][0])

    if value and "/" not in value and ":" not in value and " " not in value:
        return TrackReference(id=value)

    raise ValueError(f"unsupported track id or URI: {value!r}")


def track_metadata(track: TrackReference, title: str = "") -> str:
    safe_title = escape(title or track.uri, quote=False)
    escaped_uri = escape(track.sonos_uri, quote=False)
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
