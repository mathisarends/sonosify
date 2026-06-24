def local_name(tag: str) -> str:
    """Strip the XML namespace from a tag, e.g. ``{ns}ZoneGroup`` -> ``ZoneGroup``."""
    return tag.rsplit("}", 1)[-1]


def int_or_none(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    return int(value)


def parse_headers(raw: str) -> tuple[str, dict[str, str]]:
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
