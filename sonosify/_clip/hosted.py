import asyncio
from collections.abc import Awaitable, Callable

from sonosify._clip.models import AudioClip
from sonosify._clip.server import AudioClipServer
from sonosify._clip.websocket import AudioClipWebSocket


class HostedAudioClip:
    def __init__(
        self,
        clip: AudioClip,
        *,
        fetched: asyncio.Event,
        server: AudioClipServer,
        token: str,
        websocket: AudioClipWebSocket,
        cancel: Callable[[str], Awaitable[None]],
    ) -> None:
        self._clip = clip
        self._fetched = fetched
        self._server = server
        self._token = token
        self._websocket = websocket
        self._cancel = cancel

    @property
    def clip(self) -> AudioClip:
        return self._clip

    @property
    def id(self) -> str:
        return self._clip.id

    @property
    def fetched(self) -> bool:
        return self._fetched.is_set()

    async def wait_until_fetched(self, *, timeout: float | None = None) -> None:
        async with asyncio.timeout(timeout):
            await self._fetched.wait()

    async def wait_until_finished(self, *, timeout: float | None = None) -> AudioClip:
        value = await self._websocket.wait_for_audio_clip(self.id, timeout=timeout)
        self._clip = AudioClip.model_validate(value)
        self._server.remove(self._token)
        return self._clip

    async def cancel(self) -> None:
        await self._cancel(self.id)

    def close(self) -> None:
        self._server.remove(self._token)
