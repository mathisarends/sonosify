from xml.etree import ElementTree

from sonosify._parsing import _find_element, _int_or_none, _local_name, _parse_headers


def test_local_name_strips_namespace() -> None:
    assert _local_name("{urn:schemas-upnp-org}ZoneGroup") == "ZoneGroup"
    assert _local_name("ZoneGroup") == "ZoneGroup"


def test_int_or_none() -> None:
    assert _int_or_none("42") == 42
    assert _int_or_none(None) is None
    assert _int_or_none("") is None
    assert _int_or_none("-1") is None
    assert _int_or_none("1.5") is None


def test_parse_headers_splits_start_line_and_casefolds_keys() -> None:
    raw = (
        "HTTP/1.1 200 OK\r\nLOCATION: http://host/x\r\nCACHE-CONTROL: max-age=1\r\n\r\n"
    )

    start_line, headers = _parse_headers(raw)

    assert start_line == "HTTP/1.1 200 OK"
    assert headers["location"] == "http://host/x"
    assert headers["cache-control"] == "max-age=1"


def test_parse_headers_empty() -> None:
    assert _parse_headers("") == ("", {})


def test_find_element_returns_none_when_tag_is_absent() -> None:
    root = ElementTree.fromstring("<root><a/></root>")
    assert _find_element(root, "missing") is None
