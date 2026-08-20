import struct


def streaming_wav_header(
    sample_rate: int, channels: int = 1, sample_width: int = 2
) -> bytes:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if sample_rate > 0xFFFFFFFF:
        raise ValueError("sample_rate is too large for a WAVE header")
    if channels <= 0:
        raise ValueError("channels must be positive")
    if channels > 0xFFFF:
        raise ValueError("channels is too large for a WAVE header")
    if sample_width <= 0:
        raise ValueError("sample_width must be positive")
    if sample_width * 8 > 0xFFFF:
        raise ValueError("sample_width is too large for a WAVE header")

    block_align = channels * sample_width
    byte_rate = sample_rate * block_align
    if block_align > 0xFFFF or byte_rate > 0xFFFFFFFF:
        raise ValueError("audio format is too large for a WAVE header")
    unknown = 0xFFFFFFFF
    return (
        b"RIFF"
        + struct.pack("<I", unknown)
        + b"WAVEfmt "
        + struct.pack(
            "<IHHIIHH",
            16,
            1,
            channels,
            sample_rate,
            byte_rate,
            block_align,
            sample_width * 8,
        )
        + b"data"
        + struct.pack("<I", unknown)
    )
