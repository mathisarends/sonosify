import asyncio
import struct

import pytest

from examples.realtime_pcm_clip import _pcm48_stereo, _play_pcm
from sonosify import streaming_wav_header


def _convert(chunks: list[bytes]) -> bytes:
    async def source():
        for chunk in chunks:
            yield chunk

    async def run() -> bytes:
        return b"".join([chunk async for chunk in _pcm48_stereo(source())])

    return asyncio.run(run())


def test_pcm_example_interpolates_and_duplicates_channels_without_changing_duration() -> (
    None
):
    pcm = struct.pack("<hhh", 0, 1000, -1000)
    converted = _convert([pcm])
    assert struct.unpack("<12h", converted) == (
        0,
        0,
        500,
        500,
        1000,
        1000,
        0,
        0,
        -1000,
        -1000,
        -1000,
        -1000,
    )
    assert len(converted) == len(pcm) * 4


def test_pcm_example_preserves_continuity_across_arbitrary_chunk_boundaries() -> None:
    pcm = struct.pack("<hhhhhh", -32768, -500, 0, 500, 32767, 1)
    assert _convert([pcm[index : index + 1] for index in range(len(pcm))]) == _convert(
        [pcm]
    )
    assert _convert([]) == b""


def test_pcm_example_rejects_an_incomplete_final_sample() -> None:
    with pytest.raises(ValueError, match="incomplete sample"):
        _convert([b"\x01"])


@pytest.mark.parametrize("cancel_turn", [False, True])
def test_pcm_example_aborts_and_closes_an_interrupted_turn(cancel_turn: bool) -> None:
    async def run() -> None:
        waiting = asyncio.Event()

        class Stream:
            aborted = False
            closed = False
            writes: list[bytes]

            def __init__(self) -> None:
                self.writes = []

            async def write(self, data: bytes) -> None:
                self.writes.append(data)

            async def abort(self) -> None:
                self.aborted = True

            def close(self) -> None:
                self.closed = True

        stream = Stream()

        class Client:
            async def stream_audio_clip(self, **kwargs: object) -> Stream:
                return stream

        async def source():
            if cancel_turn:
                yield struct.pack("<hh", 100, 200)
                waiting.set()
                await asyncio.Event().wait()
            else:
                yield b"a"

        playback = asyncio.create_task(_play_pcm(Client(), source()))  # type: ignore[arg-type]
        try:
            if cancel_turn:
                await asyncio.wait_for(waiting.wait(), timeout=1.0)
                playback.cancel()
            with pytest.raises(asyncio.CancelledError if cancel_turn else ValueError):
                await playback
            assert stream.aborted
            assert stream.closed
            assert stream.writes[0] == streaming_wav_header(48_000, channels=2)
        finally:
            playback.cancel()
            await asyncio.gather(playback, return_exceptions=True)

    asyncio.run(run())
