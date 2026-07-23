from typing import Any, override

from sonosify.errors import SonosifyError


class SonosCloudError(SonosifyError):
    """Base error for Sonos Control API operations."""

    @override
    def error_details(self) -> dict[str, object]:
        return {"code": "cloud_error"}


class CloudConfigurationError(SonosCloudError):
    """Raised when required cloud credentials or settings are missing."""

    __slots__ = ("missing",)

    def __init__(self, *missing: str) -> None:
        self.missing = tuple(missing)
        names = ", ".join(self.missing)
        super().__init__(f"missing Sonos cloud configuration: {names}")

    @override
    def error_details(self) -> dict[str, object]:
        return {
            "code": "cloud_configuration_error",
            "missing": list(self.missing),
        }


class CloudAuthenticationError(SonosCloudError):
    """Raised when Sonos rejects an OAuth operation."""

    @override
    def error_details(self) -> dict[str, object]:
        return {"code": "cloud_authentication_error"}


class CloudTargetError(SonosCloudError):
    """Raised when a cloud player/group target cannot be resolved uniquely."""

    @override
    def error_details(self) -> dict[str, object]:
        return {"code": "cloud_target_error"}


class CloudConnectionError(SonosCloudError):
    """Raised when the Sonos cloud cannot be reached."""

    @override
    def error_details(self) -> dict[str, object]:
        return {"code": "cloud_connection_error"}


class CloudAPIError(SonosCloudError):
    """A structured error returned by the Sonos Control API."""

    __slots__ = ("details", "error_code", "status_code")

    def __init__(
        self,
        status_code: int,
        *,
        error_code: str = "",
        details: Any = None,
    ) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.details = details
        message = f"Sonos Control API returned HTTP {status_code}"
        if error_code:
            message = f"{message}: {error_code}"
        super().__init__(message)

    @override
    def error_details(self) -> dict[str, object]:
        result: dict[str, object] = {
            "code": "cloud_api_error",
            "status_code": self.status_code,
        }
        if self.error_code:
            result["sonos_code"] = self.error_code
        if isinstance(self.details, dict):
            result["details"] = self.details
        return result
