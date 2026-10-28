import contextlib
from collections.abc import AsyncIterable

from .models import AudioClip
from .stream import AudioClipStream


async def _play_pcm(
    stream: AudioClipStream,
    chunks: AsyncIterable[bytes],
    *,
    header: bytes,
    frame_size: int,
) -> AudioClip:
    written = 0
    try:
        # Start the player's fetch while the producer generates its first chunk.
        await stream.write(header)
        async for chunk in chunks:
            await stream.write(chunk)
            written += len(chunk)
        if not written:
            raise ValueError("PCM stream must not be empty")
        if written % frame_size:
            raise ValueError("PCM stream ended with an incomplete frame")
        await stream.end()
        return await stream.wait_until_finished()
    except BaseException:
        # Preserve the producer error or cancellation if the player is unreachable.
        with contextlib.suppress(Exception):
            await stream.abort()
        raise
    finally:
        stream.close()
