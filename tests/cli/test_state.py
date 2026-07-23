from sonosify.cli.state import CliState, OutputFormat


def test_default_state() -> None:
    state = CliState()

    assert state.format == OutputFormat.PLAIN
    assert state.debug is False
    assert state.timeout > 0


def test_configure_overrides_all_fields() -> None:
    state = CliState()

    state.configure(format=OutputFormat.JSON, debug=True, timeout=7.5)

    assert state.format == OutputFormat.JSON
    assert state.debug is True
    assert state.timeout == 7.5


def test_output_format_values() -> None:
    assert OutputFormat.PLAIN == "plain"
    assert OutputFormat.JSON == "json"
    assert OutputFormat.TSV == "tsv"
