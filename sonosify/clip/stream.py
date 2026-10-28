import asyncio
from collections.abc import Awaitable, Callable

from ..errors import NetworkError
from .models import AudioClip
from .server import _STREAM_END, AudioClipServer, _StreamedAudio
from .websocket import AudioClipWebSocket


class AudioClipStream:
    def __init__(
        self,
        *,
        streamed: _StreamedAudio,
        server: AudioClipServer,
        token: str,
        websocket: AudioClipWebSocket,
        load: Callable[[], Awaitable[AudioClip]],
        cancel: Callable[[str], Awaitable[None]],
        prebuffer_bytes: int,
    ) -> None:
        self._streamed = streamed
        self._server = server
        self._token = token
        self._websocket = websocket
        self._load = load
        self._cancel = cancel
        self._prebuffer_bytes = prebuffer_bytes
        self._prefix: list[bytes] = []
        self._written_bytes = 0
        self._clip: AudioClip | None = None
        self._ended = False
        self._aborted = False
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def clip(self) -> AudioClip:
        if self._clip is None:
            raise RuntimeError("audio clip has not been loaded yet")
        return self._clip

    @property
    def id(self) -> str:
        return self.clip.id

    @property
    def fetched(self) -> bool:
        return self._streamed.requested.is_set()

    async def write(self, data: bytes) -> None:
        if not data:
            return
        async with self._lock:
            self._ensure_writable()
            if self._clip is None:
                self._prefix.append(data)
                self._written_bytes += len(data)
                if self._written_bytes < self._prebuffer_bytes:
                    return
                await self._start()
                return
            await self._put(data)

    async def end(self) -> None:
        async with self._lock:
            self._ensure_writable()
            if self._written_bytes == 0:
                raise ValueError("audio clip stream must not be empty")
            if self._clip is None:
                await self._start()
            await self._put(_STREAM_END)
            self._ended = True

    async def abort(self) -> None:
        # Wake writers waiting for queue space before waiting for their lock.
        self._streamed.close()
        async with self._lock:
            if self._aborted:
                return
            self._aborted = True
            self._prefix.clear()
            self._server.remove(self._token)
            if self._clip is not None:
                await asyncio.shield(self._cancel(self._clip.id))

    async def wait_until_fetched(self, *, timeout: float | None = None) -> None:
        async with asyncio.timeout(timeout):
            await self._streamed.requested.wait()

    async def wait_until_finished(self, *, timeout: float | None = None) -> AudioClip:
        if self._clip is None:
            raise RuntimeError("audio clip has not been loaded yet")
        value = await self._websocket.wait_for_audio_clip(
            self._clip.id, timeout=timeout
        )
        self._clip = AudioClip.model_validate(value)
        self._server.remove(self._token)
        return self._clip

    def close(self) -> None:
        self._closed = True
        self._prefix.clear()
        self._streamed.close()
        self._server.remove(self._token)

    async def _start(self) -> None:
        try:
            # Make buffered audio available before the player can request it.
            prefix = b"".join(self._prefix)
            self._prefix.clear()
            await self._put(prefix)
            self._clip = await self._load()
        except BaseException:
            self._prefix.clear()
            self._server.remove(self._token)
            raise

    async def _put(self, item: bytes | object) -> None:
        if self._streamed.disconnected.is_set():
            raise NetworkError("Sonos player disconnected from audio clip stream")
        if self._streamed.closed.is_set() or self._streamed.unavailable.is_set():
            raise NetworkError("audio clip stream was closed")
        try:
            self._streamed.queue.put_nowait(item)
            return
        except asyncio.QueueFull:
            pass
        put = asyncio.create_task(self._streamed.queue.put(item))
        unavailable = asyncio.create_task(self._streamed.unavailable.wait())
        try:
            done, _ = await asyncio.wait(
                {put, unavailable}, return_when=asyncio.FIRST_COMPLETED
            )
            if unavailable in done:
                if self._streamed.disconnected.is_set():
                    raise NetworkError(
                        "Sonos player disconnected from audio clip stream"
                    )
                raise NetworkError("audio clip stream was closed")
            await put
        finally:
            put.cancel()
            unavailable.cancel()
            await asyncio.gather(put, unavailable, return_exceptions=True)

    def _ensure_writable(self) -> None:
        if self._aborted:
            raise RuntimeError("audio clip stream was aborted")
        if self._closed:
            raise RuntimeError("audio clip stream was closed")
        if self._ended:
            raise RuntimeError("audio clip stream has ended")
