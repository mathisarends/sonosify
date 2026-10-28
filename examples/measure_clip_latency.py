"""Measure PCM delivery and Sonos clip status on one explicitly selected player.

ACTIVE is the player's reported status, not an acoustic onset measurement.
A negative PCM-to-HTTP time means the player was primed before PCM arrived.

    uv run python examples/measure_clip_latency.py --ip 192.168.1.20
    uv run python examples/measure_clip_latency.py --ip 192.168.1.20 --formats 24000:1 24000:2 48000:2 --prebuffer-ms 0 100 --repeat 3 --output results.json
"""

import argparse
import asyncio
import json
import math
import platform
import statistics
import struct
from pathlib import Path
from time import perf_counter

from sonosify import ClipPriority, ClipType, SonosClient, streaming_wav_header


async def _measure(
    client: SonosClient,
    *,
    sample_rate: int,
    channels: int,
    prebuffer_ms: int,
    repeat: int,
    duration: float,
    chunk_ms: int,
    volume: int,
) -> dict[str, object]:
    samples = (
        int(4500 * math.sin(2 * math.pi * 440 * frame / sample_rate))
        for frame in range(round(sample_rate * duration))
        for _ in range(channels)
    )
    pcm = b"".join(struct.pack("<h", sample) for sample in samples)
    chunk_bytes = max(1, round(sample_rate * chunk_ms / 1000)) * channels * 2
    states: dict[str, dict[str, float]] = {}
    websocket = client._audio_clip_websocket
    dispatch = websocket._dispatch_event

    def observe(header, body):
        # Protocol timestamps avoid polling and its timer-dependent latency.
        now = perf_counter()
        for clip in body.get("audioClips", []):
            if isinstance(clip, dict) and isinstance(clip.get("id"), str):
                states.setdefault(clip["id"], {}).setdefault(
                    clip.get("status", ""), now
                )
        dispatch(header, body)

    websocket._dispatch_event = observe
    started = perf_counter()
    stream = None
    fetched = None
    try:
        stream = await client.stream_audio_clip(
            app_id="sonosify.latency-benchmark",
            name="PCM latency test",
            volume=volume,
            priority=ClipPriority.HIGH,
            clip_type=ClipType.CUSTOM,
            prebuffer_bytes=round(prebuffer_ms * sample_rate * channels * 2 / 1000),
        )
        ready = perf_counter()

        async def record_fetch() -> float:
            await stream.wait_until_fetched(timeout=10)
            return perf_counter()

        fetched = asyncio.create_task(record_fetch())
        await stream.write(streaming_wav_header(sample_rate, channels))
        # Model generation may overlap stream setup; don't count it as library delay.
        origin = perf_counter() + 0.2
        first_pcm = None
        write_times = []
        for offset in range(0, len(pcm), chunk_bytes):
            deadline = origin + offset / (sample_rate * channels * 2)
            delay = deadline - perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            if first_pcm is None:
                first_pcm = perf_counter()
            before = perf_counter()
            await stream.write(pcm[offset : offset + chunk_bytes])
            write_times.append((perf_counter() - before) * 1000)
        await stream.end()
        fetched_at = await fetched
        result = await stream.wait_until_finished(timeout=duration + 10)
        active = states.get(stream.id, {}).get("ACTIVE")
        assert first_pcm is not None
        return {
            "sample_rate": sample_rate,
            "channels": channels,
            "prebuffer_ms": prebuffer_ms,
            "repeat": repeat,
            "stream_setup_ms": (ready - started) * 1000,
            "pcm_to_http_ms": (fetched_at - first_pcm) * 1000,
            "pcm_to_active_ms": (active - first_pcm) * 1000 if active else None,
            "write_p50_ms": statistics.median(write_times),
            "write_p95_ms": sorted(write_times)[math.ceil(0.95 * len(write_times)) - 1],
            "status": result.status.value if result.status else None,
        }
    except BaseException:
        if stream is not None:
            await asyncio.shield(stream.abort())
        raise
    finally:
        if fetched is not None:
            fetched.cancel()
            await asyncio.gather(fetched, return_exceptions=True)
        if stream is not None:
            stream.close()
        websocket._dispatch_event = dispatch


def _format(value: str) -> tuple[int, int]:
    try:
        rate, channels = map(int, value.split(":"))
        streaming_wav_header(rate, channels)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError(
            "use SAMPLE_RATE:CHANNELS, e.g. 24000:1"
        ) from error
    return rate, channels


async def _main(args: argparse.Namespace) -> None:
    records = []
    try:
        async with SonosClient(args.ip) as client:
            for repeat in range(1, args.repeat + 1):
                for sample_rate, channels in args.formats:
                    for prebuffer_ms in args.prebuffer_ms:
                        record = await _measure(
                            client,
                            sample_rate=sample_rate,
                            channels=channels,
                            prebuffer_ms=prebuffer_ms,
                            repeat=repeat,
                            duration=args.duration,
                            chunk_ms=args.chunk_ms,
                            volume=args.volume,
                        )
                        records.append(record)
                        print(json.dumps(record), flush=True)
                        await asyncio.sleep(0.25)
    finally:
        if args.output:
            args.output.write_text(
                json.dumps(
                    {
                        "platform": platform.platform(),
                        "python": platform.python_version(),
                        "records": records,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True)
    parser.add_argument(
        "--formats",
        nargs="+",
        type=_format,
        default=[(24000, 1), (24000, 2), (48000, 2)],
    )
    parser.add_argument("--prebuffer-ms", nargs="+", type=int, default=[0])
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--chunk-ms", type=int, default=20)
    parser.add_argument("--volume", type=int, default=8)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.duration <= 0 or arguments.chunk_ms <= 0 or arguments.repeat <= 0:
        parser.error("duration, chunk-ms, and repeat must be positive")
    if any(value < 0 for value in arguments.prebuffer_ms):
        parser.error("prebuffer-ms must not be negative")
    asyncio.run(_main(arguments))
