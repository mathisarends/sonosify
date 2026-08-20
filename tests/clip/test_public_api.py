from sonosify.clip import (
    AudioClip,
    AudioClipStream,
    ClipLEDBehavior,
    ClipPriority,
    ClipStatus,
    ClipType,
    HostedAudioClip,
    streaming_wav_header,
)


def test_clip_package_exports_supported_api() -> None:
    assert AudioClip
    assert AudioClipStream
    assert ClipLEDBehavior
    assert ClipPriority
    assert ClipStatus
    assert ClipType
    assert HostedAudioClip
    assert streaming_wav_header
