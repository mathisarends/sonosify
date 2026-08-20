import io
import struct
import wave

import pytest

from sonosify import streaming_wav_header


def test_streaming_wav_header_describes_unbounded_pcm() -> None:
    header = streaming_wav_header(24_000, channels=1, sample_width=2)

    assert len(header) == 44
    assert header[:12] == b"RIFF\xff\xff\xff\xffWAVE"
    assert header[40:44] == struct.pack("<I", 0xFFFFFFFF)
    with wave.open(io.BytesIO(header)) as wav:
        assert wav.getframerate() == 24_000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == 2_147_483_647


@pytest.mark.parametrize("field", ["sample_rate", "channels", "sample_width"])
def test_streaming_wav_header_rejects_nonpositive_values(field: str) -> None:
    values = {"sample_rate": 24_000, "channels": 1, "sample_width": 2}
    values[field] = 0

    with pytest.raises(ValueError, match=field):
        streaming_wav_header(**values)


@pytest.mark.parametrize(
    "values",
    [
        {"sample_rate": 0x1_0000_0000},
        {"sample_rate": 24_000, "channels": 0x1_0000},
        {"sample_rate": 0xFFFFFFFF, "channels": 2, "sample_width": 2},
    ],
)
def test_streaming_wav_header_rejects_fields_that_do_not_fit(
    values: dict[str, int],
) -> None:
    with pytest.raises(ValueError, match="too large"):
        streaming_wav_header(**values)
