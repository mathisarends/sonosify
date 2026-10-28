"""Forward 24 kHz mono PCM16 to one Sonos audio clip.

Use decoded response.output_audio.delta bytes as the input iterator, and end
that iterator at response.output_audio.done. Cancelling the playback task
aborts the clip, which is useful when the user starts a new turn.

Try an existing raw PCM file with realtime pacing:
    uv run python examples/realtime_pcm_clip.py speech.pcm --ip 192.168.1.20
"""

import argparse
import asyncio
import struct
from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path

from sonosify import (
    AudioClip,
    ClipPriority,
    ClipType,
    SonosClient,
    streaming_wav_header,
)


async def _pcm48_stereo(chunks: AsyncIterable[bytes]) -> AsyncIterator[bytes]:
    # A one-sample linear interpolator avoids a resampler dependency for this
    # voice example. In Era 100 measurements, the higher byte rate reduced
    # startup delay; pitch and duration stay unchanged.
    previous: int | None = None
    pending = b""
    async for chunk in chunks:
        data = pending + chunk
        aligned = len(data) // 2 * 2
        pending = data[aligned:]
        output = bytearray(aligned * 4)
        offset = 0
        for (sample,) in struct.iter_unpack("<h", data[:aligned]):
            if previous is not None:
                midpoint = (previous + sample) // 2
                struct.pack_into(
                    "<hhhh", output, offset, previous, previous, midpoint, midpoint
                )
                offset += 8
            previous = sample
        if offset:
            yield bytes(output[:offset])
    if pending:
        raise ValueError("PCM16 stream ended with an incomplete sample")
    if previous is not None:
        yield struct.pack("<hhhh", previous, previous, previous, previous)


async def _play_pcm(
    client: SonosClient,
    chunks: AsyncIterable[bytes],
    *,
    volume: int = 8,
    timeout: float = 60.0,
) -> AudioClip:
    stream = await client.stream_audio_clip(
        app_id="sonosify.realtime-pcm",
        name="Realtime PCM",
        volume=volume,
        priority=ClipPriority.HIGH,
        clip_type=ClipType.CUSTOM,
        prebuffer_bytes=0,
    )
    try:
        # Prime the player before awaiting the first model-generated PCM chunk.
        await stream.write(streaming_wav_header(48_000, channels=2))
        async for chunk in _pcm48_stereo(chunks):
            await stream.write(chunk)
        await stream.end()
        return await stream.wait_until_finished(timeout=timeout)
    except BaseException:
        await asyncio.shield(stream.abort())
        raise
    finally:
        stream.close()


async def _pcm_file(path: Path) -> AsyncIterator[bytes]:
    loop = asyncio.get_running_loop()
    started = loop.time()
    sent = 0
    with path.open("rb") as audio:
        while chunk := audio.read(960):
            delay = started + sent / 48_000 - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            yield chunk
            sent += len(chunk)


async def _main(args: argparse.Namespace) -> None:
    async with SonosClient(args.ip) as client:
        result = await _play_pcm(client, _pcm_file(args.pcm_file), volume=args.volume)
        print(f"clip finished: {result.status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcm_file", type=Path, help="raw PCM16 LE, 24 kHz, mono")
    parser.add_argument("--ip", required=True, help="one player's IP; skips discovery")
    parser.add_argument("--volume", type=int, default=8)
    asyncio.run(_main(parser.parse_args()))
