import asyncio
from unittest.mock import AsyncMock

import pytest

from sonosify import AudioClip, SonosClient, streaming_wav_header


class _Stream:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.ended = False
        self.aborted = False
        self.closed = False
        self.clip = AudioClip(id="pcm-1", name="pcm", app_id="test")

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def end(self) -> None:
        self.ended = True

    async def wait_until_finished(self) -> AudioClip:
        return self.clip

    async def abort(self) -> None:
        self.aborted = True

    def close(self) -> None:
        self.closed = True


def test_play_pcm_wraps_arbitrary_chunks_and_owns_stream() -> None:
    async def run() -> None:
        stream = _Stream()
        async with SonosClient("192.0.2.1") as client:
            factory = AsyncMock(return_value=stream)
            client.stream_audio_clip = factory

            async def chunks():
                yield b"a"
                yield b"bcd"

            result = await client.play_pcm(
                chunks(), sample_rate=24_000, app_id="test", prebuffer_seconds=0.1
            )
            assert result is stream.clip
            assert stream.writes == [streaming_wav_header(24_000), b"a", b"bcd"]
            assert stream.ended and stream.closed and not stream.aborted
            assert factory.call_args.kwargs["prebuffer_bytes"] == 44 + 4800

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["empty", "frame", "producer", "cancel", "timeout"])
def test_play_pcm_aborts_and_closes_on_failure(failure: str) -> None:
    async def run() -> None:
        stream = _Stream()
        started = asyncio.Event()
        async with SonosClient("192.0.2.1") as client:
            client.stream_audio_clip = AsyncMock(return_value=stream)

            async def chunks():
                if failure == "empty":
                    return
                if failure == "frame":
                    yield b"a"
                elif failure == "producer":
                    raise LookupError("producer failed")
                else:
                    yield b"ab"
                    started.set()
                    await asyncio.Event().wait()

            playback = asyncio.create_task(
                client.play_pcm(
                    chunks(),
                    sample_rate=24_000,
                    app_id="test",
                    timeout=0.05 if failure == "timeout" else 1,
                )
            )
            if failure == "cancel":
                await asyncio.wait_for(started.wait(), timeout=1)
                playback.cancel()
            expected = {
                "producer": LookupError,
                "cancel": asyncio.CancelledError,
                "timeout": TimeoutError,
            }.get(failure, ValueError)
            with pytest.raises(expected):
                await playback
            assert stream.writes[0] == streaming_wav_header(24_000)
            assert stream.aborted and stream.closed

    asyncio.run(run())


@pytest.mark.parametrize("prebuffer", [-1.0, float("nan"), float("inf")])
def test_play_pcm_validates_before_opening_stream(prebuffer: float) -> None:
    async def run() -> None:
        async with SonosClient("192.0.2.1") as client:
            factory = AsyncMock()
            client.stream_audio_clip = factory

            async def chunks():
                yield b"ab"

            with pytest.raises(ValueError, match="prebuffer_seconds"):
                await client.play_pcm(
                    chunks(),
                    sample_rate=24_000,
                    app_id="test",
                    prebuffer_seconds=prebuffer,
                )
            factory.assert_not_awaited()

    asyncio.run(run())


def test_play_pcm_preserves_producer_error_if_abort_fails() -> None:
    async def run() -> None:
        stream = _Stream()
        stream.abort = AsyncMock(side_effect=RuntimeError("player unreachable"))
        async with SonosClient("192.0.2.1") as client:
            client.stream_audio_clip = AsyncMock(return_value=stream)

            async def chunks():
                raise LookupError("producer failed")
                yield b""  # pragma: no cover

            with pytest.raises(LookupError, match="producer failed"):
                await client.play_pcm(chunks(), sample_rate=24_000, app_id="test")
            assert stream.closed

    asyncio.run(run())
