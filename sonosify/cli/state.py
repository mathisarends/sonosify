from enum import StrEnum

from sonosify.client import DEFAULT_TIMEOUT


class OutputFormat(StrEnum):
    PLAIN = "plain"
    JSON = "json"
    TSV = "tsv"


class CliState:
    __slots__ = ("_debug", "_format", "_timeout")

    def __init__(
        self,
        *,
        format: OutputFormat = OutputFormat.PLAIN,
        debug: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._format = format
        self._debug = debug
        self._timeout = timeout

    @property
    def format(self) -> OutputFormat:
        return self._format

    @property
    def debug(self) -> bool:
        return self._debug

    @property
    def timeout(self) -> float:
        return self._timeout

    def configure(self, *, format: OutputFormat, debug: bool, timeout: float) -> None:
        self._format = format
        self._debug = debug
        self._timeout = timeout


state = CliState()
