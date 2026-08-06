from xml.etree import ElementTree

from sonosify._parsing import local_name
from sonosify.events.models import (
    RawEventValues,
    SonosEvent,
    event_type,
    normalize_service,
)

# LastChange wraps its variables in a per-instance container; Queue uses QueueID
# where the AV services use InstanceID.
_LAST_CHANGE_CONTAINERS = frozenset({"Event", "InstanceID", "QueueID"})
_MASTER_CHANNEL = "Master"


def parse_notify_event(
    raw: str | bytes, *, service: str, sid: str = "", sequence: int | None = None
) -> SonosEvent:
    values = _property_values(raw)
    normalized = normalize_service(service)
    return event_type(service).model_validate(
        {
            **values,
            "service": normalized or service,
            "values": values,
            "sequence": sequence,
            "sid": sid,
        }
    )


def parse_last_change(raw: str) -> RawEventValues:
    if not raw:
        return {}
    values: RawEventValues = {}
    for element in ElementTree.fromstring(raw).iter():
        name = local_name(element.tag)
        value = element.attrib.get("val")
        if value is None or name in _LAST_CHANGE_CONTAINERS:
            continue
        # Stereo pairs repeat channel-scoped variables; keep the Master value
        # under the plain name so it cannot be overwritten by LF/RF.
        channel = element.attrib.get("channel", _MASTER_CHANNEL)
        values[name if channel == _MASTER_CHANNEL else f"{name}:{channel}"] = value
    return values


def _property_values(raw: str | bytes) -> RawEventValues:
    values: RawEventValues = {}
    for property_element in ElementTree.fromstring(raw).iter():
        if local_name(property_element.tag) != "property":
            continue
        for child in property_element:
            name = local_name(child.tag)
            text = child.text or ""
            if name == "LastChange":
                values.update(parse_last_change(text))
            else:
                values[name] = text
    return values
