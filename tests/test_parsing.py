from sonosify._parsing import int_or_none, local_name, parse_headers


def test_local_name_strips_namespace() -> None:
    assert local_name("{urn:schemas-upnp-org}ZoneGroup") == "ZoneGroup"
    assert local_name("ZoneGroup") == "ZoneGroup"


def test_int_or_none() -> None:
    assert int_or_none("42") == 42
    assert int_or_none(None) is None
    assert int_or_none("") is None
    assert int_or_none("-1") is None
    assert int_or_none("1.5") is None


def test_parse_headers_splits_start_line_and_casefolds_keys() -> None:
    raw = "HTTP/1.1 200 OK\r\nLOCATION: http://host/x\r\nCACHE-CONTROL: max-age=1\r\n\r\n"

    start_line, headers = parse_headers(raw)

    assert start_line == "HTTP/1.1 200 OK"
    assert headers["location"] == "http://host/x"
    assert headers["cache-control"] == "max-age=1"


def test_parse_headers_empty() -> None:
    assert parse_headers("") == ("", {})
