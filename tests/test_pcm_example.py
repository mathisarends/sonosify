import asyncio
import struct

import pytest

from examples.realtime_pcm_clip import _pcm48_stereo


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
