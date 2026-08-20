import asyncio
import concurrent.futures
import logging
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

_STREAM_QUEUE_SIZE = 32
_QUEUE_POLL_SECONDS = 0.25
_STREAM_END = object()


class _HostedAudio:
    def __init__(
        self,
        audio: bytes,
        content_type: str,
        fetched: asyncio.Event,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.audio = audio
        self.content_type = content_type
        self.fetched = fetched
        self.loop = loop


class _StreamedAudio:
    def __init__(self, content_type: str, loop: asyncio.AbstractEventLoop) -> None:
        self.content_type = content_type
        self.loop = loop
        self.queue: asyncio.Queue[bytes | object] = asyncio.Queue(
            maxsize=_STREAM_QUEUE_SIZE
        )
        self.requested = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.unavailable = asyncio.Event()
        self.closed = threading.Event()
        self.request_count = 0

    def close(self) -> None:
        self.closed.set()
        self.loop.call_soon_threadsafe(self.unavailable.set)


class AudioClipServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 0) -> None:
        self._clips: dict[str, _HostedAudio | _StreamedAudio] = {}
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer((host, port), self._build_handler())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="sonosify-audio-clip-http",
            daemon=True,
        )
        self._thread.start()

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def add(self, audio: bytes, content_type: str) -> tuple[str, asyncio.Event]:
        extension = ".wav" if content_type == "audio/wav" else ".mp3"
        token = f"{uuid.uuid4().hex}{extension}"
        fetched = asyncio.Event()
        hosted = _HostedAudio(
            audio,
            content_type,
            fetched,
            asyncio.get_running_loop(),
        )
        with self._lock:
            self._clips[token] = hosted
        return token, fetched

    def add_stream(self, content_type: str) -> tuple[str, _StreamedAudio]:
        extension = ".wav" if content_type == "audio/wav" else ".mp3"
        token = f"{uuid.uuid4().hex}{extension}"
        streamed = _StreamedAudio(content_type, asyncio.get_running_loop())
        with self._lock:
            self._clips[token] = streamed
        return token, streamed

    def remove(self, token: str) -> None:
        with self._lock:
            clip = self._clips.pop(token, None)
        if isinstance(clip, _StreamedAudio):
            clip.close()

    def close(self) -> None:
        with self._lock:
            streams = [
                clip
                for clip in self._clips.values()
                if isinstance(clip, _StreamedAudio)
            ]
        for stream in streams:
            stream.close()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
        with self._lock:
            self._clips.clear()

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        clips = self._clips
        lock = self._lock

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _lookup(self) -> _HostedAudio | _StreamedAudio | None:
                with lock:
                    return clips.get(self.path.lstrip("/"))

            def _send_headers(self, hosted: _HostedAudio | _StreamedAudio) -> None:
                self.send_response(200)
                self.send_header("Content-Type", hosted.content_type)
                if isinstance(hosted, _HostedAudio):
                    self.send_header("Content-Length", str(len(hosted.audio)))
                else:
                    self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Accept-Ranges", "none")
                self.end_headers()

            def do_HEAD(self) -> None:  # noqa: N802 - http.server naming
                hosted = self._lookup()
                if hosted is None:
                    self.send_error(404)
                    return
                if isinstance(hosted, _StreamedAudio):
                    self.send_response(200)
                    self.send_header("Content-Type", hosted.content_type)
                    self.send_header("Accept-Ranges", "none")
                    self.end_headers()
                    return
                self._send_headers(hosted)

            def do_GET(self) -> None:  # noqa: N802 - http.server naming
                token = self.path.lstrip("/")
                hosted = self._lookup()
                if hosted is None:
                    self.send_error(404)
                    return
                if isinstance(hosted, _StreamedAudio):
                    with lock:
                        hosted.request_count += 1
                        first_request = hosted.request_count == 1
                    if not first_request:
                        self.send_error(409, "audio stream already requested")
                        return
                    self._stream(hosted)
                    return
                self._send_headers(hosted)
                try:
                    self.wfile.write(hosted.audio)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                hosted.loop.call_soon_threadsafe(hosted.fetched.set)
                with lock:
                    clips.pop(token, None)

            def _stream(self, streamed: _StreamedAudio) -> None:
                self._send_headers(streamed)
                streamed.loop.call_soon_threadsafe(streamed.requested.set)
                pending: concurrent.futures.Future[bytes | object] | None = None
                try:
                    while not streamed.closed.is_set():
                        if pending is None:
                            pending = asyncio.run_coroutine_threadsafe(
                                streamed.queue.get(), streamed.loop
                            )
                        try:
                            item = pending.result(timeout=_QUEUE_POLL_SECONDS)
                        except TimeoutError:
                            continue
                        pending = None
                        if item is _STREAM_END:
                            self.wfile.write(b"0\r\n\r\n")
                            self.wfile.flush()
                            return
                        assert isinstance(item, bytes)
                        self.wfile.write(f"{len(item):X}\r\n".encode("ascii"))
                        self.wfile.write(item)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    streamed.loop.call_soon_threadsafe(streamed.disconnected.set)
                    streamed.loop.call_soon_threadsafe(streamed.unavailable.set)
                finally:
                    if pending is not None:
                        pending.cancel()
                    if streamed.closed.is_set():
                        self.close_connection = True

            def log_message(self, format: str, *args: object) -> None:
                logger.debug("Sonos HTTP %s - %s", self.address_string(), format % args)

        return _Handler


def _local_ip_for(remote_ip: str) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((remote_ip, 1400))
        return str(sock.getsockname()[0])
    finally:
        sock.close()
