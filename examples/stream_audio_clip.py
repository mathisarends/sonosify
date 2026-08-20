"""Stream a generated tone and report real Sonos startup/backpressure timings.

Run with discovery:
    uv run python examples/stream_audio_clip.py Kitchen

Or target a player directly:
    uv run python examples/stream_audio_clip.py --ip 192.168.1.20
"""

import argparse
import asyncio
import math
import struct
from time import perf_counter

from sonosify import (
    ClipPriority,
    ClipType,
    SonosController,
    streaming_wav_header,
)

_SAMPLE_RATE = 24_000
_CHANNELS = 1
_SAMPLE_WIDTH = 2


def _tone(seconds: float, frequency: float) -> bytes:
    frames = int(_SAMPLE_RATE * seconds)
    return b"".join(
        struct.pack(
            "<h",
            int(10_000 * math.sin(2 * math.pi * frequency * frame / _SAMPLE_RATE)),
        )
        for frame in range(frames)
    )


async def _main(args: argparse.Namespace) -> None:
    controller = SonosController()
    async with await controller.client(args.room, ip=args.ip) as client:
        prebuffer_bytes = int(args.prebuffer * _SAMPLE_RATE * _CHANNELS * _SAMPLE_WIDTH)
        started = perf_counter()
        stream = await client.stream_audio_clip(
            app_id="sonosify.streaming-probe",
            name="Streaming probe",
            volume=args.volume,
            priority=ClipPriority.HIGH,
            clip_type=ClipType.CUSTOM,
            prebuffer_bytes=prebuffer_bytes,
        )

        async def record_fetch_time() -> float:
            await stream.wait_until_fetched(timeout=5.0)
            return perf_counter()

        fetch_time = asyncio.create_task(record_fetch_time())
        await stream.write(streaming_wav_header(_SAMPLE_RATE, _CHANNELS))

        write_latencies: list[float] = []
        written_bytes = len(streaming_wav_header(_SAMPLE_RATE, _CHANNELS))
        loaded_at: float | None = None
        chunks = math.ceil(args.duration / args.chunk)
        for index in range(chunks):
            before_write = perf_counter()
            chunk = _tone(args.chunk, 440 + index % 5 * 80)
            await stream.write(chunk)
            write_latencies.append(perf_counter() - before_write)
            written_bytes += len(chunk)
            if loaded_at is None and written_bytes >= prebuffer_bytes:
                loaded_at = perf_counter()
            await asyncio.sleep(args.chunk / args.delivery_rate)

        await stream.end()
        queued = perf_counter()
        fetched = await fetch_time
        if loaded_at is not None:
            print(f"loadAudioClip completed: {loaded_at - started:.3f}s")
        print(f"player HTTP fetch observed: {fetched - started:.3f}s")
        print(f"producer feed completed: {queued - started:.3f}s")
        print(f"slowest write/backpressure: {max(write_latencies) * 1000:.1f}ms")
        print("Did the stepped tone start promptly and play without gaps?")
        result = await stream.wait_until_finished(timeout=args.duration + 15.0)
        finished = perf_counter()
        print(f"terminal status: {result.status} after {finished - started:.3f}s")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("room", nargs="?")
    parser.add_argument("--ip")
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--chunk", type=float, default=0.25)
    parser.add_argument("--delivery-rate", type=float, default=2.0)
    parser.add_argument("--prebuffer", type=float, default=1.5)
    parser.add_argument("--volume", type=int)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(_main(_parse_args()))
