# Streaming audio clips in sonosify

Implementation plan for adding an incremental (push-based) audio-clip API to
`sonosify`, so callers can start playback before the audio exists.

Target version: `sonosify` 0.4.4 (installed here). Consumer that motivates it:
`voice/src/voice/audio/output/sonos.py` in `cara`.

---

## 1. Why

`SonosOutput` in `cara` buffers the entire TTS response before it plays anything,
because `play_audio_clip_data(audio: bytes)` needs the complete body up front.
Time-to-first-sound therefore scales linearly with response length.

Measured against Deepgram `aura-2` (the current provider):

| | |
|---|---|
| delivery rate | **~2.0x realtime**, WebSocket and REST alike |
| model | `wall ~= 0.4s + audio_duration / 2` (holds from 0.5s to 21s of audio) |
| a 20s answer | **~10s** of pure TTS wait before the clip is even built |

The rate is not bandwidth-bound: `linear16@24k` (973 KB), `linear16@8k` (335 KB)
and `mulaw@8k` (165 KB) all took ~10s for the same text. It is server-side
pacing. No client change fixes it — the fix is to stop waiting for the last byte.

The same buffering existed while Cartesia was wired up (verified in git:
`0c4bebd^` had `CartesiaTextToSpeech` + `SonosOutput` with the identical
`play_chunk` that only does `self._pcm.extend(chunk)`). It simply did not hurt,
because Cartesia's throughput left much more headroom. So this is not a
Deepgram-specific workaround: it removes a length-proportional delay that every
provider pays.

**Headroom note that drives the design:** at 2.0x realtime the producer is only
2x faster than the consumer. A streaming clip must therefore prebuffer before
playback starts, or a single network hiccup underruns mid-sentence.

---

## 2. What the infrastructure already does

`play_audio_clip_data` is already a two-channel design, which is exactly what
streaming needs. Nothing has to be invented, only extended.

```
client.play_audio_clip_data(audio)
  |- _get_or_fetch_player_id()                       HTTP  -> device_description.xml
  |- _audio_clip_websocket.subscribe_audio_clips()   WS    -> audioClip:1 subscribe
  |- _ensure_audio_clip_server()                     starts ThreadingHTTPServer (daemon thread)
  |- server.add(audio, content_type) -> token, fetched
  |- play_audio_clip(stream_url=http://<host>:<port>/<token>)
  |                                                  WS    -> loadAudioClip
  |  ... player fetches the URL over HTTP ...
  \- HostedAudioClip.wait_until_finished()           WS    <- audioClipStatus -> DONE
```

Relevant properties of the current implementation:

- `clip/server.py` — `AudioClipServer` is a `ThreadingHTTPServer` on a daemon
  thread. Bodies are `bytes` in a dict guarded by a `threading.Lock`. The
  handler sends `Content-Length`, writes the whole body, then signals the
  asyncio side with `hosted.loop.call_soon_threadsafe(hosted.fetched.set)` and
  **pops the token**. The cross-thread bridge back into the event loop already
  exists — the streaming path needs the same bridge in the other direction.
- `BaseHTTPRequestHandler.protocol_version` is left at its default `HTTP/1.0`,
  so chunked transfer-encoding is currently not available.
- `clip/websocket.py` — `AudioClipWebSocket` is a persistent, multiplexed
  connection with a reader task, a response future, and per-clip status waiters.
  It is already long-lived and reused across clips. **The streaming work needs
  no change here.**
- `clip/hosted.py` — `HostedAudioClip` bundles the clip, the `fetched` event,
  the server token, the websocket and a cancel callback.

---

## 3. Hardware gate: the assumption that could kill the plan

Everything below depended on a single hardware-specific fact:

> **Does a Sonos player accept an `audioClip` whose `streamUrl` returns a body of
> unknown length?**

`audioClip` is designed for short notification sounds, not for radio-style
streams. Sonos players do handle unbounded streams elsewhere (internet radio),
but that is a different code path on the device. This must be answered on real
hardware before any API is designed around it.

### Hardware result (2026-08-20)

Variant A was validated on a Sonos Era 100 using the implemented
`examples/stream_audio_clip.py` probe. The producer delivered six
seconds of PCM in 250 ms chunks at 2.0x realtime with a 1.5 second prebuffer.

| Measurement | Result |
| --- | ---: |
| Player HTTP fetch | **0.809 s from stream creation** |
| Slowest awaited `write()` | **7.6 ms** |
| Terminal status | **DONE at 6.870 s** |

This answers R1 positively and R3 with `DONE`: the player accepts HTTP/1.1
chunked WAV data of unknown length and completes when the terminating chunk is
sent. The successful single-consumer run also did not trigger the server's
second-GET rejection. R4 and R5 remain separate hardware experiments.

Two candidate framings were considered; variant A passed, so B was not needed:

- **A — HTTP/1.1 + `Transfer-Encoding: chunked`.** Requires setting
  `protocol_version = "HTTP/1.1"` on the handler.
- **B — HTTP/1.0, no `Content-Length`, body delimited by connection close.**
  Closer to how Sonos consumes shoutcast/icecast streams.

A local prototype of variant A (threading HTTP server fed from an asyncio
producer, `httpx` as the client) works: first byte after 94 ms, body streams
through, one request. The WAV placeholder header below also parses
(`wave.open` reports `nframes=2147483647`). So the mechanics are sound — only
the player's acceptance is open.

### Probe script

Run against a real speaker before writing library code. It answers R1–R3 at once.

```python
# probe_stream.py — answers: does the player accept an unbounded clip body?
import asyncio, math, queue, struct, threading, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from sonosify import ClipPriority, ClipType, SonosController
from sonosify.clip.server import _local_ip_for

SENTINEL = object()
CHUNKED = True          # flip to False to test variant B
RATE, CHANNELS = 24000, 1


def wav_header(rate, channels, width=2):
    br, ba, unknown = rate * channels * width, channels * width, 0xFFFFFFFF
    return (b"RIFF" + struct.pack("<I", unknown) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate, br, ba, width * 8)
            + b"data" + struct.pack("<I", unknown))


def tone(seconds, freq=440):
    n = int(RATE * seconds)
    return b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / RATE)))
                    for i in range(n))


class Probe:
    def __init__(self):
        self.q, self.log = queue.Queue(), []
        self.server = ThreadingHTTPServer(("0.0.0.0", 0), self._handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.token = f"{uuid.uuid4().hex}.wav"

    @property
    def port(self):
        return self.server.server_address[1]

    def _handler(self):
        probe = self

        class Handler(BaseHTTPRequestHandler):
            if CHUNKED:
                protocol_version = "HTTP/1.1"

            def do_HEAD(self):
                probe.log.append(("HEAD", self.path, dict(self.headers)))
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.end_headers()

            def do_GET(self):
                probe.log.append(("GET", self.path, dict(self.headers)))
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Accept-Ranges", "none")
                if CHUNKED:
                    self.send_header("Transfer-Encoding", "chunked")
                else:
                    self.send_header("Connection", "close")
                self.end_headers()
                try:
                    while (item := probe.q.get()) is not SENTINEL:
                        if CHUNKED:
                            self.wfile.write(f"{len(item):X}".encode() + b"\r\n")
                            self.wfile.write(item)
                            self.wfile.write(b"\r\n")
                        else:
                            self.wfile.write(item)
                        self.wfile.flush()
                    if CHUNKED:
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    probe.log.append(("DISCONNECT", self.path, {}))

            def log_message(self, *args):
                pass

        return Handler


async def main():
    probe = Probe()
    client = await SonosController().client(None)   # or ip=...
    url = f"http://{_local_ip_for(client.ip)}:{probe.port}/{probe.token}"
    print("serving", url)

    probe.q.put(wav_header(RATE, CHANNELS))
    probe.q.put(tone(1.0))                      # prebuffer

    clip = await client.play_audio_clip(
        url, app_id="probe", name="probe",
        priority=ClipPriority.HIGH, clip_type=ClipType.CUSTOM,
    )
    print("loadAudioClip ->", clip)

    for i in range(8):                          # keep feeding after playback started
        await asyncio.sleep(0.8)
        probe.q.put(tone(1.0, 440 + i * 60))
        print(f"  fed chunk {i}")
    probe.q.put(SENTINEL)

    await asyncio.sleep(12)
    print("\nHTTP log:")
    interesting = {"range", "user-agent", "connection", "icy-metadata"}
    for method, path, headers in probe.log:
        print(" ", method, path,
              {k: v for k, v in headers.items() if k.lower() in interesting})
    probe.server.shutdown()
    await client.close()


asyncio.run(main())
```

**What to record:**

| # | Question | How the log answers it |
|---|---|---|
| R1 | Does the player play an unbounded body at all? | you hear the tone; `loadAudioClip` returns non-ERROR |
| R2 | How many HTTP requests per clip? HEAD first? Range headers? | the printed `HTTP log` |
| R3 | Does the clip reach `DONE` when the body ends, or hang? | subscribe and watch `audioClipStatus` |
| R4 | How long may the body stall before the player gives up? | insert a deliberate `await asyncio.sleep(N)` mid-stream, bisect N |
| R5 | Is there still a minimum clip duration? | `cara` pads to 1.5s today; test a 0.3s stream |

**R2 matters for the API.** If the player issues a probe request and then a
second real GET, a single-shot queue is not enough — the server would have to
replay the already-sent prefix. The design below assumes one GET; if the probe
shows otherwise, add a prefix buffer (noted in §6).

If R1 comes back negative, stop. The fallback is segment-wise clips (one clip
per sentence), which needs no sonosify change at all and is a `cara`-side
change only.

---

## 4. Proposed API

### 4.1 What I want

**Primitive: a push-based writer handle.** TTS is push-based — audio arrives via
callbacks, not from an iterable the caller can hand over. The primitive must
match that, and the pull-based form is trivial sugar on top.

```python
class AudioClipStream:
    """A Sonos audio clip whose body is written incrementally."""

    @property
    def id(self) -> str: ...
    @property
    def clip(self) -> AudioClip: ...
    @property
    def fetched(self) -> bool: ...

    async def write(self, data: bytes) -> None: ...
    async def end(self) -> None: ...
    async def abort(self) -> None: ...
    async def wait_until_fetched(self, *, timeout: float | None = None) -> None: ...
    async def wait_until_finished(self, *, timeout: float | None = None) -> AudioClip: ...
    def close(self) -> None: ...
```

```python
class SonosClient:
    async def stream_audio_clip(
        self,
        *,
        content_type: str = "audio/wav",
        prebuffer_bytes: int = 0,
        local_host: str | None = None,
        app_id: str,
        name: str = "sonosify",
        volume: int | None = None,
        priority: ClipPriority = ClipPriority.LOW,
        clip_type: ClipType | None = None,
        led_behavior: ClipLEDBehavior = ClipLEDBehavior.NONE,
    ) -> AudioClipStream: ...
```

Three deliberate choices:

1. **`loadAudioClip` is deferred until `prebuffer_bytes` have been written.**
   This is the most important knob in the whole design. Issuing `loadAudioClip`
   immediately means the player opens the GET against an empty queue and sits
   there; with only 2x throughput headroom that is exactly where underruns come
   from. `stream_audio_clip()` returns as soon as the stream exists; the WS
   command fires from inside the first `write()` that crosses the threshold (or
   from `end()`, whichever comes first). `prebuffer_bytes=0` keeps the eager
   behaviour for callers that know their producer is fast.

2. **`wait_until_fetched()` means "the player opened the GET".** For
   `HostedAudioClip` the event fires when the body is fully written; for a
   stream that would be useless. Different semantics, so it is a different
   class rather than a flag on the existing one.

3. **`abort()` is distinct from `end()`.** `end()` closes the body and lets
   playback run out; `abort()` sends `cancelAudioClip` *and* tears down the HTTP
   body immediately. Barge-in needs the second one, and the current
   `HostedAudioClip.cancel()` only does the WS half.

**One format helper**, because a streaming RIFF header is the one non-obvious
piece every caller would otherwise reimplement:

```python
def streaming_wav_header(
    sample_rate: int, channels: int = 1, sample_width: int = 2
) -> bytes:
    """RIFF/WAVE header with placeholder sizes, for a body of unknown length."""
```

It writes `0xFFFFFFFF` into the RIFF and `data` size fields. Verified locally:
`wave.open` accepts it and reports an unbounded frame count.

### 4.2 What I explicitly do not want

- **No encoders, no resampling, no PCM knowledge in the core path.**
  `stream_audio_clip` takes container bytes and pipes them, exactly like
  `play_audio_clip_data` does. Adding `lameenc` for MP3 would pull in a build
  dependency and add encode latency to the very path we are optimizing. If MP3
  turns out to be the only container Sonos will stream, producing it is the
  caller's job.
- **No asyncio rewrite of `AudioClipServer`.** The daemon thread plus a
  cross-thread bridge is enough. Rewriting it on `asyncio.start_server` would
  touch the working buffered path for no benefit and balloon the PR.
- **No behaviour change to `play_audio_clip_data` or `HostedAudioClip`.**
  They stay exactly as they are. Streaming is additive.
- **No Range / seek support.** `Accept-Ranges: none` stays. A stream cannot
  satisfy a range request.
- **No automatic retry or reconnect** if the player drops the connection
  mid-stream. Surface it as an error; the caller decides.
- **No `AsyncIterable` overload on the same method.** If pull-based sugar is
  wanted, add a separate `play_audio_clip_stream(chunks: AsyncIterable[bytes])`
  that wraps the primitive. Overloading one method with both shapes makes the
  cancellation semantics ambiguous.

---

## 5. Implementation

### 5.1 `clip/server.py` — teach the handler to stream

Add a second body type alongside `_HostedAudio`:

```python
class _StreamedAudio:
    def __init__(self, content_type, queue, loop, requested):
        self.content_type = content_type
        self.queue = queue          # asyncio.Queue[bytes | object], owned by the loop
        self.loop = loop
        self.requested = requested  # asyncio.Event
        self.request_count = 0
```

`AudioClipServer` gains:

```python
def add_stream(self, content_type: str) -> tuple[str, _StreamedAudio]: ...
```

Handler changes:

- Set `protocol_version = "HTTP/1.1"` (needed for chunked). This also affects
  the buffered path — harmless there, since it sends `Content-Length`, and it
  additionally enables keep-alive. Call it out in the PR description.
- `do_GET` branches on the body type. Streaming branch:
  - `send_response(200)`, `Content-Type`, `Accept-Ranges: none`,
    `Transfer-Encoding: chunked`, `end_headers()`
  - signal `requested` via `loop.call_soon_threadsafe(...)` — the pattern
    already used for `fetched`
  - loop: pull the next chunk, write it framed, `flush()`
  - on sentinel: write the terminating `0\r\n\r\n`
  - on `BrokenPipeError` / `ConnectionResetError`: mark the stream as
    disconnected so the async side's `write()` fails instead of blocking forever
- Do **not** pop the token on first GET for streams (the buffered path still
  does). Removal is explicit via `remove(token)` from `close()`/`abort()`.

**Cross-thread queue.** The handler thread must consume from an asyncio-owned
queue. Use the mirror of the existing `call_soon_threadsafe` bridge:

```python
future = asyncio.run_coroutine_threadsafe(stream.queue.get(), stream.loop)
item = future.result(timeout=STALL_TIMEOUT)
```

This gives real async backpressure for free — make it a **bounded**
`asyncio.Queue`, and `AudioClipStream.write()` awaits naturally when the player
is slower than the producer. `STALL_TIMEOUT` should be derived from R4.

A simpler alternative if that feels too clever: a bounded `queue.Queue` with
`await asyncio.to_thread(q.put, chunk)` on the async side. Correct, but one
thread-pool hop per chunk (~50/s for 20 ms TTS chunks).

### 5.2 `clip/stream.py` — new, the public handle

`AudioClipStream` holds: the token, the `_StreamedAudio`, the server, the
websocket, the `cancel` callback, the deferred-load state, and the
`prebuffer_bytes` threshold.

- `write(data)` — appends to the queue; once the cumulative byte count reaches
  `prebuffer_bytes` and the clip has not been loaded yet, awaits the deferred
  `loadAudioClip` first, then continues. Raises if the stream was aborted or the
  player disconnected.
- `end()` — flushes the deferred load if it never fired (short clip), pushes the
  sentinel.
- `abort()` — pushes the sentinel, `remove(token)`, and sends `cancelAudioClip`
  if the clip was loaded. Must be safe to call twice and safe to call from a
  cancellation handler (mirror the `asyncio.shield` care that `cara`'s
  `SonosOutput._wait_for_clip` already applies).
- `wait_until_finished()` — same as `HostedAudioClip`: delegate to
  `websocket.wait_for_audio_clip(self.id, timeout=...)`, then `remove(token)`.

### 5.3 `clip/wav.py` — new, tiny

`streaming_wav_header()` as specified in §4.1. Pure function, no I/O.

### 5.4 `client.py`

`stream_audio_clip(...)` mirrors `play_audio_clip_data` up to the point of the
WS command:

```python
player_id = await self._get_or_fetch_player_id()
await self._audio_clip_websocket.subscribe_audio_clips(player_id)
server = self._ensure_audio_clip_server()
token, streamed = server.add_stream(content_type)
host = local_host or _local_ip_for(self._ip)
stream_url = f"http://{host}:{server.port}/{token}"
return AudioClipStream(
    stream_url=stream_url, token=token, streamed=streamed, server=server,
    websocket=self._audio_clip_websocket,
    load=functools.partial(self.play_audio_clip, stream_url, app_id=app_id, ...),
    cancel=self.cancel_audio_clip,
    prebuffer_bytes=prebuffer_bytes,
)
```

Reuse `_validate_audio_clip_arguments` and the same `content_type` whitelist.

### 5.5 `clip/__init__.py` and `sonosify/__init__.py`

Export `AudioClipStream` and `streaming_wav_header` from the public
`sonosify.clip` package and the package root. Keep `AudioClipServer`,
`AudioClipWebSocket` and `_local_ip_for` out of `sonosify.clip` exports; the
probe imports the helper from its implementation module deliberately.

---

## 6. Edge cases the PR must handle

| Case | Handling |
|---|---|
| Player never fetches the URL | timeout in `wait_until_fetched`; `close()` must free the queue and token |
| Player disconnects mid-stream | handler catches `BrokenPipeError`; the async side's next `write()` raises rather than blocking forever |
| Second GET for the same token (R2) | v1: log and reject with 409. If the probe shows the player routinely re-requests, add a bounded prefix buffer and replay it |
| `end()` without any `write()` | must not send `loadAudioClip` for an empty body — raise, matching `play_audio_clip_data`'s "must not be empty" |
| `abort()` before load fired | skip `cancelAudioClip`, just tear down locally |
| Very short stream (R5) | document that the caller pads; do not silently pad inside the library |
| `client.close()` with a live stream | `AudioClipServer.close()` must unblock handler threads, otherwise `self._thread.join()` hangs |
| Concurrent streams | tokens already isolate them; verify the buffered and streaming paths coexist on one server instance |

---

## 7. Tests

Unit / integration without hardware (this is most of it):

- `streaming_wav_header` — byte-exact header, and `wave.open` accepts it
- `AudioClipServer.add_stream` + a real `httpx` client against `127.0.0.1`:
  chunked framing correct, first byte arrives before the producer finishes,
  terminating chunk sent
- backpressure: bounded queue, slow reader, assert `write()` actually suspends
- disconnect: client closes early, assert the next `write()` raises
- `prebuffer_bytes`: assert `loadAudioClip` is not sent before the threshold and
  is sent exactly once
- `abort()` idempotency, and `abort()` before/after load
- `client.close()` with a live stream terminates (regression guard for the
  `_thread.join()` hang)

Hardware test: keep the §3 probe in the repo as a manual script.

---

## 8. How `cara` consumes it

`voice/src/voice/audio/output/sonos.py` becomes genuinely streaming, and the
`AudioOutput` port already has the right shape:

```python
async def start(self, *, sample_rate, channels):
    client = await self._resolve_client()
    self._stream = await client.stream_audio_clip(
        app_id=_CLIP_APP_ID, name=_CLIP_NAME,
        volume=await self._clip_volume(client),
        priority=ClipPriority.HIGH, clip_type=ClipType.CUSTOM,
        led_behavior=ClipLEDBehavior.WHITE_LED_QUICK_BREATHING,
        prebuffer_bytes=_PREBUFFER_SECONDS * sample_rate * channels * 2,
    )
    await self._stream.write(streaming_wav_header(sample_rate, channels))

async def play_chunk(self, chunk):
    await self._stream.write(chunk)

async def finish_response(self):
    await self._stream.end()
    result = await self._stream.wait_until_finished()
    ...

async def clear_buffer(self):
    await self._stream.abort()
```

`_PREBUFFER_SECONDS` is the knob that pays for Deepgram's thin 2x margin.
Start at ~1.5s and tune against R4. Expected time-to-first-sound afterwards:
`LLM first sentence + ~0.4s Deepgram + prebuffer + clip fetch`, i.e. roughly
constant instead of proportional to the answer length.

Two `cara`-side follow-ups that are independent of this PR and were measured
alongside: Deepgram opens a fresh WebSocket per turn (~0.7s, avoidable by
reusing the connection the way the Cartesia client already does), and sending an
early `Flush` after the first ~40 characters cuts time-to-first-audio from
1.19s to 0.52s. Both belong in `vocalbin`, not here.
