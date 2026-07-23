# sonosify

![sonosify banner](static/sonosify_banner.png)

Programmatic Python API for discovering and controlling Sonos speakers on a local network.

This package ports the API core of `steipete/sonoscli` into Python. An optional
command-line interface is available via the `cli` extra (see below).

```python
import asyncio

from sonosify import SonosController


async def main():
    sonos = SonosController()
    system = await sonos.discover()

    print([speaker.room_name for speaker in system.speakers])

    async with await sonos.client("Kitchen") as kitchen:
        await kitchen.pause()
        await kitchen.set_volume(25)
        print(await kitchen.now_playing())


asyncio.run(main())
```

Lower-level direct device access is also available:

```python
import asyncio

from sonosify import SonosClient


async def main():
    async with SonosClient("192.168.1.42") as speaker:
        await speaker.play_uri("https://example.com/live.mp3", radio=True, title="Example Radio")


asyncio.run(main())
```

Live updates use Sonos UPnP event subscriptions:

```python
import asyncio

from sonosify import AVTransportEvent, RenderingControlEvent, SonosController


async def main():
    sonos = SonosController()
    async with sonos.watch("Kitchen") as watcher:
        async for event in watcher:
            match event:
                case AVTransportEvent(transport_state=state, track=track):
                    print(state, track.title if track else "")
                case RenderingControlEvent(volume=volume, muted=muted):
                    print(volume, muted)


asyncio.run(main())
```

The watch API starts a local HTTP callback server. Your OS firewall may ask whether Python can accept incoming connections.

See `examples/` for runnable scripts:

```powershell
uv run python examples/discover.py
uv run python examples/now_playing.py Kitchen
uv run python examples/watch.py Kitchen
uv run python examples/play_radio.py Kitchen https://example.com/live.mp3 "Example Radio"
```

## Command-line interface

Install the optional CLI dependencies (Typer + Rich):

```powershell
uv pip install -e ".[cli]"
# or, from PyPI: pip install "sonosify[cli]"
```

This exposes a `sonosify` command:

```powershell
sonosify discover --format json
sonosify status --room Kitchen --format json
sonosify play --room Kitchen
sonosify pause --all
sonosify set-volume 25 --room Kitchen
sonosify set-volume 20 --group "Living Room"
sonosify mute --room Kitchen --on
sonosify queue --room Kitchen
sonosify queue jump 7 --room Kitchen
sonosify seek 1:30 --room Kitchen
sonosify shuffle on --room Kitchen
sonosify repeat all --room Kitchen
sonosify crossfade on --room Kitchen
sonosify sleep 30m --room Kitchen
sonosify group "Living Room" --with Kitchen --with Office
sonosify ungroup --room Kitchen
sonosify groups --format json
sonosify ping --room Kitchen --format json
sonosify watch --room Kitchen --count 5 --format json
```

### Targeting a speaker

Every speaker command accepts `--room/-r` and `--ip`. Existing positional room
arguments remain available for compatibility. `--ip` opens the device directly and
does not perform SSDP discovery. A successful `discover` refreshes the persistent
room-to-IP cache; exact room names use that cache and fall back to discovery on a
cache miss.

### Default speaker

Set a default speaker once and omit the room name from then on:

```powershell
sonosify config set --room Kitchen      # or: sonosify config set --ip 192.168.1.42
sonosify config show                    # show current defaults
sonosify config clear                   # remove defaults

sonosify play                           # now targets Kitchen automatically
sonosify volume 25                      # set Kitchen to 25
sonosify volume-up
```

An explicit room name or `--ip` on a command always overrides the configured default.
The config is stored as JSON in your platform's app-config directory.

The same defaults can be supplied without writing a file:

```powershell
$env:SONOSIFY_ROOM = "Kitchen"
$env:SONOSIFY_IP = "192.168.1.42"
$env:SONOSIFY_FORMAT = "json"
$env:SONOSIFY_TIMEOUT = "5"
$env:SONOSIFY_DEBUG = "1"
```

Precedence is command-line flag, then environment, then config file.

### Output format

Use `--format` before or after a command:

```powershell
sonosify --format json discover         # JSON speaker-list envelope
sonosify --format tsv queue --room Kitchen  # tab-separated rows
sonosify status --format json            # JSON object
```

`plain` (the default) renders rich tables and colored text for interactive use.
Machine-readable stdout contains only result data. Diagnostics and debug traces go
to stderr.

JSON output has `schema_version: 1`. Object/action commands add their fields beside
it. List commands use this stable envelope:

```json
{"schema_version": 1, "items": [{"room": "Kitchen", "ip": "192.168.1.42"}]}
```

`now-playing` and `status` include numeric `position_s` and `duration_s`.
`status` combines playback state, volume, mute state, track, group identifier, and
timing in one call.

`watch --format json` emits one object per line (NDJSON). It can terminate itself
with `--count N`, `--duration 10s`, or `--until PLAYING`.

### Errors and exit codes

In JSON mode, failures are emitted as a JSON object on stderr while stdout remains
empty:

```json
{"schema_version": 1, "error": "no speaker matching 'Kitcen'", "code": "speaker_not_found", "query": "Kitcen"}
```

Stable exit codes are:

| Exit | Meaning |
|------|---------|
| `0` | Success |
| `1` | Other sonosify error |
| `2` | Speaker not found |
| `3` | Ambiguous speaker (`matches` is included in JSON) |
| `4` | Discovery or network failure / timeout |
| `5` | Sonos UPnP error (`upnp_code` and `description` are included) |

### Queue, groups, and playback modes

Queue management is available through `queue clear`, `queue remove POSITION`, and
`queue jump POSITION`. `group`, `ungroup`, and `groups` expose multi-room grouping.
Playback automation includes in-track `seek`, `shuffle`, `repeat`, `crossfade`, and
the `sleep` timer.

The legacy overloaded `volume` command remains available. Agents should prefer the
unambiguous `get-volume` and `set-volume` commands.

Use `sonosify commands --format json` for recursive command/parameter
introspection and `sonosify --version --format json` for feature detection.

### Debugging

Add `--debug` to print the underlying SOAP request/response
traces to stderr:

```powershell
sonosify --debug volume Kitchen
```

`sonosify track ...` expects a track id, track URI, or track URL. Playback works when
the corresponding music service is already linked on your Sonos household.

Exports are collected in `sonosify.__init__` for library consumers. The agent CLI
work also adds `RepeatMode`, `NetworkError`, `SonosClient.seek`,
`get_play_mode`/`set_play_mode`, `set_shuffle`, `set_repeat`,
`get_crossfade`/`set_crossfade`, and `configure_sleep_timer` to the Python API.
