import pytest

from sonosify.cli.state import CliState, OutputFormat


def test_cli_state_has_one_explicit_mutation_boundary() -> None:
    state = CliState()

    state.configure(format=OutputFormat.JSON, debug=True, timeout=3.0)

    assert (state.format, state.debug, state.timeout) == (
        OutputFormat.JSON,
        True,
        3.0,
    )
    with pytest.raises(AttributeError):
        state.timeout = 5.0  # type: ignore[misc]
