from urllib.parse import urlparse as _urlparse


def _validate_audio_clip_arguments(
    *,
    stream_url: str | None,
    app_id: str,
    name: str,
    volume: int | None,
    http_authorization: str | None,
) -> None:
    if not 1 <= len(name) <= 64:
        raise ValueError("audio clip name must contain 1 to 64 characters")
    if not app_id or len(app_id) > 127:
        raise ValueError("app_id must contain 1 to 127 characters")
    if volume is not None and not 0 <= volume <= 100:
        raise ValueError("audio clip volume must be between 0 and 100")
    if stream_url is not None:
        parsed = _urlparse(stream_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("stream_url must be an absolute HTTP(S) URL")
    if http_authorization is not None and len(http_authorization.encode()) > 512:
        raise ValueError("http_authorization must contain at most 512 bytes")
