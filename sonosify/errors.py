from collections.abc import Sequence


class SonosifyError(Exception):
    pass


class UnsupportedFeatureError(SonosifyError):
    pass


class DiscoveryError(SonosifyError):
    pass


class SpeakerNotFoundError(SonosifyError):
    __slots__ = ("_query",)

    def __init__(self, message: str, *, query: str | None = None) -> None:
        self._query = query
        super().__init__(message)

    @property
    def query(self) -> str | None:
        return self._query


class AmbiguousSpeakerError(SonosifyError):
    __slots__ = ("_matches", "_query")

    def __init__(self, query: str, matches: Sequence[str]) -> None:
        self._query = query
        self._matches = tuple(matches)
        super().__init__(
            f"ambiguous speaker {query!r}; matches: {', '.join(self._matches)}"
        )

    @property
    def query(self) -> str:
        return self._query

    @property
    def matches(self) -> tuple[str, ...]:
        return self._matches


class UPnPError(SonosifyError):
    __slots__ = ("_code", "_description")

    def __init__(self, code: str, description: str = "") -> None:
        self._code = code
        self._description = description
        message = f"upnp error {code}"
        if description:
            message = f"{message}: {description}"
        super().__init__(message)

    @property
    def code(self) -> str:
        return self._code

    @property
    def description(self) -> str:
        return self._description
