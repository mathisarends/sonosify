from xml.etree import ElementTree

from sonosify._parsing import local_name
from sonosify.didl import parse_track_metadata

from .models import (
    KNOWN_EVENT_ADAPTER,
    AVTransportValues,
    EventService,
    RawEventValues,
    RenderingControlValues,
    SonosEvent,
    UnknownSonosEvent,
    normalize_service,
)


def parse_notify_event(
    raw: str | bytes, *, service: str, sid: str = "", sequence: int | None = None
) -> SonosEvent:
    values: RawEventValues = {}
    root = ElementTree.fromstring(raw)
    for property_element in root.iter():
        if local_name(property_element.tag) != "property":
            continue
        for child in list(property_element):
            name = local_name(child.tag)
            text = child.text or ""
            if name == "LastChange":
                values.update(parse_last_change(text))
            else:
                values[name] = text

    normalized_service = normalize_service(service)
    if normalized_service is None:
        return UnknownSonosEvent(
            service=service, values=values, sequence=sequence, sid=sid
        )

    event_data: dict[str, object] = {
        "service": normalized_service,
        "values": values,
        "sequence": sequence,
        "sid": sid,
    }
    if normalized_service == EventService.AV_TRANSPORT:
        av = AVTransportValues.model_validate(values)
        metadata = av.current_track_metadata or av.enqueued_metadata
        event_data.update(
            track=parse_track_metadata(
                metadata,
                uri=av.current_track_uri,
                duration=av.current_track_duration,
                position=av.current_track,
            )
            if metadata
            else None,
            transport_state=av.transport_state,
        )
    else:
        rc = RenderingControlValues.model_validate(values)
        event_data.update(volume=rc.volume, muted=rc.muted)
    return KNOWN_EVENT_ADAPTER.validate_python(event_data)


def parse_last_change(raw: str) -> RawEventValues:
    if not raw:
        return {}
    root = ElementTree.fromstring(raw)
    values: RawEventValues = {}
    for element in root.iter():
        name = local_name(element.tag)
        if name in {"Event", "InstanceID"}:
            continue
        value = element.attrib.get("val")
        if value is not None:
            values[name] = value
    return values
