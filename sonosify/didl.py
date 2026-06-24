from html import escape
from xml.etree import ElementTree

from .models import Favorite, Track

DIDL_NS = "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
DC_NS = "http://purl.org/dc/elements/1.1/"
UPNP_NS = "urn:schemas-upnp-org:metadata-1-0/upnp/"
RINCON_NS = "urn:schemas-rinconnetworks-com:metadata-1-0/"


def parse_track_metadata(metadata: str, *, uri: str = "", duration: str = "", position: int | None = None) -> Track:
    if not metadata:
        return Track(uri=uri, duration=duration, position=position)

    try:
        root = ElementTree.fromstring(metadata)
    except ElementTree.ParseError:
        return Track(uri=uri, duration=duration, position=position)

    item = _first(root, "item")
    if item is None:
        item = root
    return Track(
        title=_text(item, "title"),
        creator=_text(item, "creator"),
        album=_text(item, "album"),
        uri=uri or _text(item, "res"),
        album_art_uri=_text(item, "albumArtURI"),
        duration=duration,
        position=position,
    )


def parse_favorites(metadata: str) -> list[Favorite]:
    if not metadata:
        return []

    try:
        root = ElementTree.fromstring(metadata)
    except ElementTree.ParseError:
        return []

    favorites: list[Favorite] = []
    for item in root.iter():
        if _local_name(item.tag) not in {"item", "container"}:
            continue
        favorites.append(
            Favorite(
                title=_text(item, "title"),
                uri=_text(item, "res"),
                metadata=ElementTree.tostring(item, encoding="unicode"),
                album_art_uri=_text(item, "albumArtURI"),
            )
        )
    return favorites


def radio_metadata(title: str, uri: str) -> str:
    safe_title = escape(title, quote=False)
    safe_uri = escape(uri, quote=False)
    return (
        f'<DIDL-Lite xmlns:dc="{DC_NS}" xmlns:upnp="{UPNP_NS}" xmlns:r="{RINCON_NS}" xmlns="{DIDL_NS}">'
        '<item id="R:0/0/0" parentID="R:0/0" restricted="true">'
        f"<dc:title>{safe_title}</dc:title>"
        '<upnp:class>object.item.audioItem.audioBroadcast</upnp:class>'
        f"<res protocolInfo=\"x-rincon-mp3radio:*:*:*\">{safe_uri}</res>"
        "</item>"
        "</DIDL-Lite>"
    )


def _first(root: ElementTree.Element, local_name: str) -> ElementTree.Element | None:
    for element in root.iter():
        if _local_name(element.tag) == local_name:
            return element
    return None


def _text(root: ElementTree.Element, local_name: str) -> str:
    element = _first(root, local_name)
    return "" if element is None or element.text is None else element.text.strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
