import json

import pytest

from sonosify.cli.output import print_action, print_object, print_records
from sonosify.cli.state import OutputFormat, state


@pytest.fixture(autouse=True)
def _reset_state():
    original = state.format
    yield
    state.configure(format=original, debug=state.debug, timeout=state.timeout)


def test_print_action_plain_uses_console(capsys: pytest.CaptureFixture[str]) -> None:
    state.configure(format=OutputFormat.PLAIN, debug=False, timeout=1.0)

    print_action("[green]done[/]", {"status": "done"})

    out = capsys.readouterr().out
    assert "done" in out


def test_print_action_json_emits_data(capsys: pytest.CaptureFixture[str]) -> None:
    state.configure(format=OutputFormat.JSON, debug=False, timeout=1.0)

    print_action("ignored", {"status": "done", "value": 3})

    out = capsys.readouterr().out.strip()
    assert json.loads(out) == {"status": "done", "value": 3}


def test_print_action_tsv_emits_values_only(capsys: pytest.CaptureFixture[str]) -> None:
    state.configure(format=OutputFormat.TSV, debug=False, timeout=1.0)

    print_action("ignored", {"status": "done", "value": 3})

    out = capsys.readouterr().out.strip()
    assert out == "done\t3"


def test_print_object_plain_calls_callback(capsys: pytest.CaptureFixture[str]) -> None:
    state.configure(format=OutputFormat.PLAIN, debug=False, timeout=1.0)
    called = False

    def plain() -> None:
        nonlocal called
        called = True

    print_object({"a": 1}, plain)

    assert called
    assert capsys.readouterr().out == ""


def test_print_object_json_emits_data(capsys: pytest.CaptureFixture[str]) -> None:
    state.configure(format=OutputFormat.JSON, debug=False, timeout=1.0)

    print_object({"a": 1}, lambda: None)

    out = capsys.readouterr().out.strip()
    assert json.loads(out) == {"a": 1}


def test_print_object_tsv_emits_key_value_lines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    state.configure(format=OutputFormat.TSV, debug=False, timeout=1.0)

    print_object({"a": 1, "b": 2}, lambda: None)

    lines = capsys.readouterr().out.strip().splitlines()
    assert lines == ["a\t1", "b\t2"]


def test_print_records_plain_calls_callback(capsys: pytest.CaptureFixture[str]) -> None:
    state.configure(format=OutputFormat.PLAIN, debug=False, timeout=1.0)
    called = False

    def plain() -> None:
        nonlocal called
        called = True

    print_records([{"a": 1}], ["a"], plain)

    assert called


def test_print_records_json_emits_list(capsys: pytest.CaptureFixture[str]) -> None:
    state.configure(format=OutputFormat.JSON, debug=False, timeout=1.0)

    print_records([{"a": 1}, {"a": 2}], ["a"], lambda: None)

    out = capsys.readouterr().out.strip()
    assert json.loads(out) == [{"a": 1}, {"a": 2}]


def test_print_records_tsv_emits_header_and_rows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    state.configure(format=OutputFormat.TSV, debug=False, timeout=1.0)

    print_records([{"a": 1, "b": 2}], ["a", "b"], lambda: None)

    lines = capsys.readouterr().out.strip().splitlines()
    assert lines == ["a\tb", "1\t2"]


def test_print_records_tsv_defaults_missing_fields_to_empty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    state.configure(format=OutputFormat.TSV, debug=False, timeout=1.0)

    print_records([{"a": 1}], ["a", "b"], lambda: None)

    lines = capsys.readouterr().out.rstrip("\n").splitlines()
    assert lines == ["a\tb", "1\t"]
