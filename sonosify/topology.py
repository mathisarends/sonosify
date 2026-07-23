from sonosify.client import DEFAULT_TIMEOUT, SonosClient
from sonosify.errors import AmbiguousSpeakerError, SpeakerNotFoundError
from sonosify.models import Group, Speaker


class SonosSystem:
    __slots__ = ("_groups", "_speakers", "_timeout")

    def __init__(
        self,
        speakers: tuple[Speaker, ...],
        groups: tuple[Group, ...],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._speakers = speakers
        self._groups = groups
        self._timeout = timeout

    @property
    def speakers(self) -> tuple[Speaker, ...]:
        return self._speakers

    @property
    def groups(self) -> tuple[Group, ...]:
        return self._groups

    @property
    def timeout(self) -> float:
        return self._timeout

    def find(
        self,
        query: str | None = None,
        *,
        ip: str | None = None,
        include_invisible: bool = False,
    ) -> Speaker:
        candidates = (
            self._speakers
            if include_invisible
            else tuple(s for s in self._speakers if not s.invisible)
        )
        if ip is not None:
            for speaker in candidates:
                if speaker.ip == ip:
                    return speaker
            raise SpeakerNotFoundError(f"no speaker with IP {ip}", query=ip)

        if not query:
            visible = [speaker for speaker in candidates if speaker.room_name]
            if len(visible) == 1:
                return visible[0]
            raise SpeakerNotFoundError(
                "room name is required when multiple speakers are available"
            )

        normalized = query.casefold()
        exact = [
            speaker
            for speaker in candidates
            if speaker.room_name.casefold() == normalized
        ]
        if len(exact) == 1:
            return exact[0]

        fuzzy = [
            speaker
            for speaker in candidates
            if normalized in speaker.room_name.casefold()
        ]
        if len(fuzzy) == 1:
            return fuzzy[0]
        if len(fuzzy) > 1:
            raise AmbiguousSpeakerError(query, [speaker.room_name for speaker in fuzzy])
        raise SpeakerNotFoundError(f"no speaker matching {query!r}", query=query)

    def coordinator_for(self, speaker: Speaker) -> Speaker:
        uid = speaker.coordinator_uid or speaker.uid
        for candidate in self._speakers:
            if candidate.uid == uid:
                return candidate
        return speaker

    def client(
        self,
        query: str | None = None,
        *,
        ip: str | None = None,
        coordinator: bool = True,
        include_invisible: bool = False,
    ) -> SonosClient:
        speaker = self.find(query, ip=ip, include_invisible=include_invisible)
        if coordinator:
            speaker = self.coordinator_for(speaker)
        return SonosClient.from_speaker(speaker, timeout=self._timeout)
