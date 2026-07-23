# 🔊 sonosify

![CI](https://github.com/mathisarends/sonosify/actions/workflows/ci.yaml/badge.svg)
![Python](https://img.shields.io/badge/python-3.13%20%7C%203.14-blue)
![PyPI](https://img.shields.io/pypi/v/sonosify)
![License](https://img.shields.io/badge/license-MIT-informational)

Programmatic Python API for discovering and controlling Sonos speakers on a local
network — plus an optional, agent-friendly command-line interface built on top of it.

![sonosify banner](static/sonosify_banner.png)

This package ports the API core of `steipete/sonoscli` into Python. It ships two
layers you can use independently:

- **Core library** (`sonosify`): an async Python API for discovery, playback,
  volume, queue, groups, favorites, and live UPnP event subscriptions.
- **Cloud API** (`sonosify.cloud`): OAuth2 and async access to the Sonos Control
  API, including Audio Clips with automatic ducking. It is part of the main
  package and adds no separate install extra.
- **CLI** (`sonosify` command, via the `cli` extra): a scriptable, JSON-first
  command-line interface designed to be driven by humans and automation/agents
  alike.

Runnable scripts covering discovery, playback, volume, queue, groups, favorites,
playback modes, and live events are in [`examples/`](examples/).

## Installation

Requires **Python 3.13 or 3.14**. Sonos speakers must be reachable on the same
local network (SSDP discovery uses UDP multicast).

Core library only:

```powershell
uv add sonosify
# or: pip install sonosify
```

With the CLI (adds Typer + Rich):

```powershell
uv add "sonosify[cli]"
# or: pip install "sonosify[cli]"
```

From a local checkout of this repository:

```powershell
uv pip install -e ".[cli]"
```

Setting up a development environment (dependency groups, tests, linting,
pre-commit) is covered in [CONTRIBUTING.md](CONTRIBUTING.md).

## Core Python API

The core API is fully async and centers on two entry points: `SonosController`
for household-wide operations (discovery, groups, watching) and `SonosClient`
for talking to one speaker directly.

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

Lower-level direct device access is also available, bypassing discovery entirely:

```python
import asyncio

from sonosify import SonosClient


async def main():
    async with SonosClient("192.168.1.42") as speaker:
        await speaker.play_uri("https://example.com/live.mp3", radio=True, title="Example Radio")


asyncio.run(main())
```

## Setting up cloud credentials

The Sonos Control API (`sonosify.cloud`) talks to Sonos's cloud service instead
of your local network, so it needs its own OAuth2 credentials. Get them from
the [Sonos Developer Platform](https://developer.sonos.com/):

1. Sign in at the [Sonos integration manager](https://integration.sonos.com/)
   and create a new integration.
2. Register a publicly routable **HTTPS** redirect URI. Sonos requires it to
   exactly match the URI your app uses to complete the OAuth flow.
3. Copy the generated **Client ID** and **Client Secret**.

Compared to the local UPnP-based core library, the Cloud API:

- Works from anywhere, without being on the same network as the speakers —
  useful for cloud-hosted bots, voice assistants, or remote automation.
- Supports Audio Clips with automatic ducking, playing short announcements
  over whatever is currently playing.
- Is an official, stable API maintained by Sonos, rather than the unofficial
  UPnP protocol the core library uses.

Once you have credentials, copy `.env.example` to `.env` and fill them in:

```powershell
Copy-Item .env.example .env
```

Configuration is loaded through `pydantic-settings`; process environment
variables take precedence over `.env`.

## Sonos Control API (`sonosify.cloud`)

See [Setting up cloud credentials](#setting-up-cloud-credentials) above to
obtain a Client ID, Client Secret, and redirect URI before using it.

The reusable API also accepts credentials explicitly:

```python
import asyncio

from sonosify.cloud.auth import SonosCloudAuth
from sonosify.cloud.client import SonosCloudClient


async def main():
    auth = SonosCloudAuth(
        client_id="YOUR_CLIENT_ID",
        client_secret="YOUR_CLIENT_SECRET",
        redirect_uri="https://agent.example.com/oauth/sonos",
    )

    # Exchange the callback's authorization code once:
    # await auth.async_exchange_code("CODE_FROM_CALLBACK")

    async with SonosCloudClient(auth, app_id="com.example.voice-agent") as sonos:
        clip = await sonos.load_audio_clip(
            "RINCON_12345678901400:1",
            "http://192.168.1.50:8000/tts/response.mp3",
            name="Agent Voice",
            volume=30,
        )
        print(clip.id)


asyncio.run(main())
```

`SonosCloudAuth` builds authorization URLs, exchanges authorization codes,
caches access/refresh tokens in the platform config directory, and refreshes
expired tokens. `SonosCloudClient` exposes households, groups and players;
player/group lookup by name; Audio Clips; playback controls, status, metadata
and seek; player/group volume; and home-theater Night Mode/Speech Enhancement.

Token persistence is injectable through `CacheHandler`. The default
`CacheFileHandler` stores the token with owner-only permissions on POSIX
systems; `MemoryCacheHandler` is useful for services that manage persistence
elsewhere or deliberately keep credentials process-local:

```python
from sonosify.cloud.auth import SonosCloudAuth
from sonosify.cloud.cache_handler import MemoryCacheHandler

auth = SonosCloudAuth(
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
    redirect_uri="https://agent.example.com/oauth/sonos",
    cache_handler=MemoryCacheHandler(),
)
```

Public classes live in the named `sonosify.cloud` modules (`auth`, `client`,
`cache_handler`, `errors`, and `models`). Names prefixed with `_`, including
endpoint URLs, OAuth scope values, settings implementation, and cache-path
selection, are private.

### Cloud CLI configuration

The `cloud` command group is always present when the CLI is installed:

```powershell
sonosify cloud auth-url
# Complete authorization, then pass the code received at the redirect URI:
sonosify cloud login AUTHORIZATION_CODE

sonosify cloud households
sonosify cloud groups
sonosify cloud players
sonosify cloud clip "http://192.168.1.50:8000/tts/response.mp3" --player Kitchen --voice --volume 30
sonosify cloud pause --group Kitchen
sonosify cloud play --group Kitchen
```

`SONOSIFY_CLOUD_ACCESS_TOKEN` can replace the login/token-cache flow for
short-lived automation. The client secret is never written to the token cache
and must remain available whenever an expired token needs refreshing. Missing
configuration produces a typed `CloudConfigurationError`; JSON CLI output
includes a `missing` list and never includes credentials or tokens.

`SonosClient` covers transport control (`play`, `pause`, `stop`, `next`,
`previous`, `seek`), volume/mute (`get_volume`, `set_volume`, `adjust_volume`,
`set_mute`, `toggle_mute`), the queue (`queue`, `enqueue_uri`, `clear_queue`,
`remove_queue_item`, `seek_queue`), playback modes (`set_shuffle`, `set_repeat`,
`set_crossfade`, `configure_sleep_timer`), grouping (`join`, `unjoin`), favorites
(`favorites`, `open_favorite`), and generic playback (`open`, `open_track`).

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

The watch API starts a local HTTP callback server. Your OS firewall may ask
whether Python can accept incoming connections.

Errors are typed and derive from `SonosifyError`: `SpeakerNotFoundError`,
`AmbiguousSpeakerError` (carries `matches`), `DiscoveryError`, `NetworkError`,
`UPnPError` (carries `code`/`description`), and `UnsupportedFeatureError`.

See `examples/` for runnable scripts:

```powershell
uv run python examples/discover.py
uv run python examples/now_playing.py Kitchen
uv run python examples/watch.py Kitchen
uv run python examples/play_radio.py Kitchen https://example.com/live.mp3 "Example Radio"
uv run python examples/resume_playback.py Kitchen
uv run python examples/volume.py Kitchen 25
uv run python examples/favorites.py Kitchen
uv run python examples/favorites.py Kitchen "Jazz FM"
uv run python examples/track_queue.py Kitchen
uv run python examples/track_queue.py Kitchen add "x-rincon-mp3radio://example.com/live.mp3"
uv run python examples/groups.py
uv run python examples/group.py join Kitchen "Living Room"
uv run python examples/group.py leave Kitchen
uv run python examples/playback_modes.py Kitchen shuffle on
uv run python examples/playback_modes.py Kitchen sleep 0:30:00
```

## Command-line interface

Install the optional CLI dependencies (Typer + Rich) as shown above, then use
the `sonosify` command:

```powershell
sonosify discover --format json
sonosify status --room Kitchen --format json
sonosify now-playing --room Kitchen
sonosify play --room Kitchen
sonosify pause --all
sonosify next --room Kitchen
sonosify previous --room Kitchen
sonosify set-volume 25 --room Kitchen
sonosify set-volume 20 --group "Living Room"
sonosify volume-up Kitchen 10
sonosify volume-down Kitchen 10
sonosify mute --room Kitchen --on
sonosify queue --room Kitchen
sonosify queue jump 7 --room Kitchen
sonosify queue remove 3 --room Kitchen
sonosify queue clear --room Kitchen
sonosify enqueue "x-rincon-mp3radio://example.com/live.mp3" --room Kitchen
sonosify open "https://example.com/live.mp3" --radio --title "Example Radio" --room Kitchen
sonosify track SPOTIFY_TRACK_ID --room Kitchen
sonosify favorites list --room Kitchen
sonosify favorites play "Jazz FM" --room Kitchen
sonosify seek 1:30 --room Kitchen
sonosify shuffle on --room Kitchen
sonosify repeat all --room Kitchen
sonosify crossfade on --room Kitchen
sonosify sleep 30m --room Kitchen
sonosify group "Living Room" --with Kitchen --with Office
sonosify ungroup --room Kitchen
sonosify groups --format json
sonosify ping --room Kitchen --format json
sonosify doctor --room Kitchen --format json
sonosify watch --room Kitchen --count 5 --format json
sonosify cloud players --format json
sonosify cloud clip "http://192.168.1.50:8000/tts/response.mp3" --player Kitchen
sonosify commands --format json
sonosify --version --format json
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

### Favorites and media

`favorites list` lists the Sonos favorites configured for a speaker's household;
`favorites play NAME` plays one by exact title or unique substring match (an
ambiguous match is rejected with the candidate titles listed). `open URL` starts
playback of an arbitrary stream URL or Sonos-playable URI (`--radio`/`--title` set
radio metadata for plain stream URLs), and `track TRACK_ID` plays a track by id,
URI, or URL from an already-linked music service (`--next` enqueues as the
next track, `--enqueue` only enqueues without starting playback).

### Queue, groups, and playback modes

Queue management is available through `queue` (show), `enqueue`, `queue clear`,
`queue remove POSITION`, and `queue jump POSITION`. `group`, `ungroup`, and
`groups` expose multi-room grouping. Playback automation includes in-track
`seek`, `shuffle`, `repeat`, `crossfade`, and the `sleep` timer.

The legacy overloaded `volume` command remains available. Agents should prefer the
unambiguous `get-volume` and `set-volume` commands.

Use `sonosify commands --format json` for recursive command/parameter
introspection and `sonosify --version --format json` for feature detection.
`sonosify doctor` runs a basic connectivity and service health check on a
speaker (round-trip latency plus a live volume read), separate from the plain
reachability check of `ping`.

### Debugging

Add `--debug` to print the underlying SOAP request/response
traces to stderr:

```powershell
sonosify --debug volume Kitchen
```

Playback of `track` and `open` works when the corresponding music service is
already linked on your Sonos household.

Exports are collected in `sonosify.__init__` for library consumers. The agent CLI
work also adds `RepeatMode`, `NetworkError`, `SonosClient.seek`,
`get_play_mode`/`set_play_mode`, `set_shuffle`, `set_repeat`,
`get_crossfade`/`set_crossfade`, and `configure_sleep_timer` to the Python API.

## Contributing

Bug reports and pull requests are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the development setup, test/lint
commands, and what CI checks on every push.

## License

MIT — see [LICENSE](LICENSE).
