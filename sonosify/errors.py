class SonosifyError(Exception):
    pass


class DiscoveryError(SonosifyError):
    pass


class SpeakerNotFoundError(SonosifyError):
    pass


class AmbiguousSpeakerError(SonosifyError):
    def __init__(self, query: str, matches: list[str]) -> None:
        self.query = query
        self.matches = matches
        super().__init__(f"ambiguous speaker {query!r}; matches: {', '.join(matches)}")


class UPnPError(SonosifyError):
    def __init__(self, code: str, description: str = "") -> None:
        self.code = code
        self.description = description
        message = f"upnp error {code}"
        if description:
            message = f"{message}: {description}"
        super().__init__(message)
