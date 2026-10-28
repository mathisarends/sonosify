from xml.etree import ElementTree as _ElementTree


def _local_name(tag: str) -> str:
    """Strip the XML namespace from a tag, e.g. ``{ns}ZoneGroup`` -> ``ZoneGroup``."""
    return tag.rsplit("}", 1)[-1]


def _int_or_none(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    return int(value)


def _parse_headers(raw: str) -> tuple[str, dict[str, str]]:
    """Parse an HTTP/SSDP message into its start line and case-folded headers."""
    lines = raw.splitlines()
    start_line = lines[0] if lines else ""
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().casefold()] = value.strip()
    return start_line, headers


def _find_element(root: _ElementTree.Element, name: str) -> _ElementTree.Element | None:
    for element in root.iter():
        if _local_name(element.tag) == name:
            return element
    return None


def _element_text(root: _ElementTree.Element, name: str) -> str:
    element = _find_element(root, name)
    return "" if element is None or element.text is None else element.text.strip()
