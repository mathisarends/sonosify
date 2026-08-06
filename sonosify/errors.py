from __future__ import annotations

from collections.abc import Sequence
from typing import override


class SonosifyError(Exception):
    """Base class for errors that have stable machine-readable CLI details."""

    def error_details(self) -> dict[str, object]:
        return {"code": "sonosify_error"}


class UnsupportedFeatureError(SonosifyError):
    @override
    def error_details(self) -> dict[str, object]:
        return {"code": "unsupported_feature"}


class DiscoveryError(SonosifyError):
    @override
    def error_details(self) -> dict[str, object]:
        return {"code": "discovery_error"}


class NetworkError(SonosifyError):
    @override
    def error_details(self) -> dict[str, object]:
        return {"code": "network_error"}


class LocalAPIError(SonosifyError):
    def __init__(
        self, message: str, *, response: dict[str, object] | None = None
    ) -> None:
        self._response = response or {}
        super().__init__(message)

    @classmethod
    def from_response(
        cls, header: dict[str, object], body: dict[str, object]
    ) -> LocalAPIError:
        response = {**header, **body}
        error_code = str(response.get("errorCode", ""))
        message = "local Sonos command failed"
        if error_code:
            message = f"{message}: {error_code}"
        return cls(message, response=response)

    @property
    def response(self) -> dict[str, object]:
        return dict(self._response)

    @override
    def error_details(self) -> dict[str, object]:
        details: dict[str, object] = {"code": "local_api_error"}
        if error_code := self._response.get("errorCode"):
            details["sonos_code"] = error_code
        return details


class SpeakerNotFoundError(SonosifyError):
    def __init__(self, message: str, *, query: str | None = None) -> None:
        self._query = query
        super().__init__(message)

    @property
    def query(self) -> str | None:
        return self._query

    @override
    def error_details(self) -> dict[str, object]:
        details: dict[str, object] = {"code": "speaker_not_found"}
        if self.query is not None:
            details["query"] = self.query
        return details


class AmbiguousSpeakerError(SonosifyError):
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

    @override
    def error_details(self) -> dict[str, object]:
        return {
            "code": "ambiguous_speaker",
            "query": self.query,
            "matches": list(self.matches),
        }


class SubscriptionError(SonosifyError):
    def __init__(self, message: str, *, services: Sequence[str] = ()) -> None:
        self._services = tuple(services)
        super().__init__(message)

    @property
    def services(self) -> tuple[str, ...]:
        return self._services

    @override
    def error_details(self) -> dict[str, object]:
        return {"code": "subscription_error", "services": list(self.services)}


class UPnPError(SonosifyError):
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

    @override
    def error_details(self) -> dict[str, object]:
        return {
            "code": "upnp_error",
            "upnp_code": self.code,
            "description": self.description,
        }
