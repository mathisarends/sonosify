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
    ClipPriority,
    ClipType,
    SonosClient,
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
        await client.prepare_audio()
        result = await client.play_pcm(
            _pcm48_stereo(_pcm_file(args.pcm_file)),
            sample_rate=48_000,
            channels=2,
            app_id="sonosify.realtime-pcm",
            name="Realtime PCM",
            volume=args.volume,
            priority=ClipPriority.HIGH,
            clip_type=ClipType.CUSTOM,
        )
        print(f"clip finished: {result.status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcm_file", type=Path, help="raw PCM16 LE, 24 kHz, mono")
    parser.add_argument("--ip", required=True, help="one player's IP; skips discovery")
    parser.add_argument("--volume", type=int, default=8)
    asyncio.run(_main(parser.parse_args()))
