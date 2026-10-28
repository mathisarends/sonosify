"""Stream incrementally produced PCM to a Sonos player.

Use discovery by room name:
    uv run python examples/stream_audio_clip.py "Kitchen"

Skip discovery for the lowest startup latency:
    uv run python examples/stream_audio_clip.py --ip 192.168.1.20
"""

import argparse
import asyncio
import math
import struct
from collections.abc import AsyncIterable, AsyncIterator
from time import perf_counter

from sonosify import (
    ClipPriority,
    ClipType,
    SonosClient,
    SonosController,
    streaming_wav_header,
)

_SAMPLE_RATE = 24_000
_CHANNELS = 1
_SAMPLE_WIDTH = 2


def _tone(seconds: float, frequency: float) -> bytes:
    frame_count = int(_SAMPLE_RATE * seconds)
    samples = (
        int(10_000 * math.sin(2 * math.pi * frequency * frame / _SAMPLE_RATE))
        for frame in range(frame_count)
    )
    return struct.pack(f"<{frame_count}h", *samples)


async def _simulated_tts(
    *,
    duration: float,
    chunk_seconds: float,
    delivery_rate: float,
    first_chunk_delay: float,
) -> AsyncIterator[bytes]:
    """Yield PCM like a TTS provider that produces audio faster than realtime."""
    chunk_count = math.ceil(duration / chunk_seconds)
    started = perf_counter()
    for index in range(chunk_count):
        deadline = started + first_chunk_delay + index * chunk_seconds / delivery_rate
        delay = deadline - perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        yield _tone(
            min(chunk_seconds, duration - index * chunk_seconds), 440 + index % 5 * 80
        )


def _report(started: float, message: str) -> None:
    print(f"[{perf_counter() - started:6.3f}s] {message}", flush=True)


async def _stream_audio(
    client: SonosClient,
    chunks: AsyncIterable[bytes],
    *,
    prebuffer_seconds: float,
    volume: int | None,
    playback_timeout: float,
    started: float,
) -> None:
    bytes_per_second = _SAMPLE_RATE * _CHANNELS * _SAMPLE_WIDTH
    prebuffer_bytes = int(prebuffer_seconds * bytes_per_second)
    stream = await client.stream_audio_clip(
        app_id="sonosify.streaming-example",
        name="Streaming example",
        volume=volume,
        priority=ClipPriority.HIGH,
        clip_type=ClipType.CUSTOM,
        prebuffer_bytes=prebuffer_bytes,
    )
    _report(started, f"stream ready; buffering {prebuffer_seconds:.2f}s of audio")

    async def report_fetch() -> None:
        await stream.wait_until_fetched(timeout=5.0)
        _report(started, "player opened the chunked HTTP stream")

    fetch_reporter = asyncio.create_task(report_fetch())
    write_latencies: list[float] = []
    header = streaming_wav_header(_SAMPLE_RATE, _CHANNELS, _SAMPLE_WIDTH)
    written_bytes = len(header)
    loaded = False

    try:
        await stream.write(header)
        if written_bytes >= prebuffer_bytes:
            loaded = True
            _report(started, "loadAudioClip completed")

        async for chunk in chunks:
            before_write = perf_counter()
            await stream.write(chunk)
            write_latencies.append(perf_counter() - before_write)
            written_bytes += len(chunk)
            if not loaded and written_bytes >= prebuffer_bytes:
                loaded = True
                _report(started, "prebuffer reached; loadAudioClip completed")

        await stream.end()
        _report(started, "producer ended; Sonos is playing buffered audio")
        await fetch_reporter
        result = await stream.wait_until_finished(timeout=playback_timeout)
        _report(started, f"playback finished with status {result.status}")
    except BaseException:
        fetch_reporter.cancel()
        await asyncio.gather(fetch_reporter, return_exceptions=True)
        await asyncio.shield(stream.abort())
        raise

    slowest_write = max(write_latencies, default=0.0) * 1000
    print(f"Slowest stream.write(): {slowest_write:.1f} ms")


async def _main(args: argparse.Namespace) -> None:
    started = perf_counter()
    target = f"IP {args.ip}" if args.ip else f"room {args.room or '(default)'}"
    _report(started, f"resolving {target}")

    controller = SonosController()
    client = await controller.client(args.room, ip=args.ip)
    _report(started, f"player ready at {client.ip}")

    chunks = _simulated_tts(
        duration=args.duration,
        chunk_seconds=args.chunk,
        delivery_rate=args.delivery_rate,
        first_chunk_delay=args.first_chunk_delay,
    )
    async with client:
        await _stream_audio(
            client,
            chunks,
            prebuffer_seconds=args.prebuffer,
            volume=args.volume,
            playback_timeout=args.duration + 15.0,
            started=started,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream a TTS-like AsyncIterator[bytes] to Sonos."
    )
    parser.add_argument("room", nargs="?", help="room name; omit with --ip")
    parser.add_argument("--ip", help="player IP; skips SSDP discovery")
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--chunk", type=float, default=0.25)
    parser.add_argument("--delivery-rate", type=float, default=2.0)
    parser.add_argument("--first-chunk-delay", type=float, default=0.4)
    parser.add_argument("--prebuffer", type=float, default=0.1)
    parser.add_argument("--volume", type=int)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(_main(_parse_args()))
