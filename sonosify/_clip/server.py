import asyncio
import logging
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)


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


class AudioClipServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 0) -> None:
        self._clips: dict[str, _HostedAudio] = {}
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

    def remove(self, token: str) -> None:
        with self._lock:
            self._clips.pop(token, None)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
        with self._lock:
            self._clips.clear()

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        clips = self._clips
        lock = self._lock

        class _Handler(BaseHTTPRequestHandler):
            def _lookup(self) -> _HostedAudio | None:
                with lock:
                    return clips.get(self.path.lstrip("/"))

            def _send_headers(self, hosted: _HostedAudio) -> None:
                self.send_response(200)
                self.send_header("Content-Type", hosted.content_type)
                self.send_header("Content-Length", str(len(hosted.audio)))
                self.send_header("Accept-Ranges", "none")
                self.end_headers()

            def do_HEAD(self) -> None:  # noqa: N802 - http.server naming
                hosted = self._lookup()
                if hosted is None:
                    self.send_error(404)
                    return
                self._send_headers(hosted)

            def do_GET(self) -> None:  # noqa: N802 - http.server naming
                token = self.path.lstrip("/")
                hosted = self._lookup()
                if hosted is None:
                    self.send_error(404)
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

            def log_message(self, fmt: str, *args: object) -> None:
                logger.debug("Sonos HTTP %s - %s", self.address_string(), fmt % args)

        return _Handler


def _local_ip_for(remote_ip: str) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((remote_ip, 1400))
        return str(sock.getsockname()[0])
    finally:
        sock.close()
