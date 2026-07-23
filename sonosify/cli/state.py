from dataclasses import dataclass
from enum import StrEnum

from sonosify.client import DEFAULT_TIMEOUT


class OutputFormat(StrEnum):
    PLAIN = "plain"
    JSON = "json"
    TSV = "tsv"


@dataclass(slots=True)
class CliState:
    format: OutputFormat = OutputFormat.PLAIN
    debug: bool = False
    timeout: float = DEFAULT_TIMEOUT


state = CliState()
