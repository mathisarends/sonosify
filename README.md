# 🔊 sonosify

![CI](https://github.com/mathisarends/sonosify/actions/workflows/ci.yaml/badge.svg)
![Python](https://img.shields.io/badge/python-3.13%20%7C%203.14-blue)
![PyPI](https://img.shields.io/pypi/v/sonosify)
![License](https://img.shields.io/badge/license-MIT-informational)

Programmatic Python API for discovering and controlling Sonos speakers on a local
network.

![sonosify banner](static/sonosify_banner.png)

This package ports the API core of `steipete/sonoscli` into Python. It ships two
layers you can use independently:

- **Core library** (`sonosify`): an async Python API for discovery, playback,
  volume, queue, groups, favorites, and live UPnP event subscriptions.
- **Cloud API** (`sonosify.cloud`): OAuth2 and async access to the Sonos Control
  API, including Audio Clips with automatic ducking. It is part of the main
  package and adds no separate install extra.

Runnable scripts covering discovery, playback, volume, queue, groups, favorites,
playback modes, and live events are in [`examples/`](examples/).

## Installation

Requires **Python 3.13 or 3.14**. Sonos speakers must be reachable on the same
local network (SSDP discovery uses UDP multicast).

```powershell
uv add sonosify
# or: pip install sonosify
```

From a local checkout of this repository:

```powershell
uv pip install -e .
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

### Local audio clips

Audio clips can also use the player's local Control API WebSocket, without
OAuth or a round trip through the Sonos cloud. Discovery is required because
the command targets the speaker's immutable player ID:

```python
import asyncio

from sonosify import ClipPriority, ClipType, SonosController


async def main():
    sonos = SonosController()
    async with await sonos.client("Kitchen") as kitchen:
        clip = await kitchen.play_audio_clip(
            "http://192.168.1.50:8000/tts/response.mp3",
            app_id="com.example.voice-agent",
            name="Agent Voice",
            volume=30,
            priority=ClipPriority.HIGH,
            clip_type=ClipType.VOICE_ASSISTANT,
        )
        print(clip.id)


asyncio.run(main())
```

The player must expose the `AUDIO_CLIP` capability, and it must be able to
fetch the supplied HTTP(S) URL itself. `cancel_audio_clip(clip.id)` cancels a
scheduled or active clip. The current implementation opens one WebSocket per
command; connection reuse can be added later without changing these methods.

## Setting up cloud credentials

The Sonos Control API (`sonosify.cloud`) talks to Sonos's cloud service instead
of your local network, so it needs its own OAuth2 credentials. Get them from
the [Sonos Developer Platform](https://developer.sonos.com/):

1. Sign in at the [Sonos integration manager](https://integration.sonos.com/)
   and create a new integration.
2. Register a redirect URI, e.g. `http://localhost:8000/callback` for local
   use. Sonos requires it to exactly match the URI your app uses to complete
   the OAuth flow.
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

from sonosify import SonosCloudAuth, SonosCloudClient


async def main():
    auth = SonosCloudAuth(
        client_id="YOUR_CLIENT_ID",
        client_secret="YOUR_CLIENT_SECRET",
        redirect_uri="https://agent.example.com/oauth/sonos",
    )

    # Exchange the callback's authorization code once:
    # await auth.async_exchange_code("CODE_FROM_CALLBACK")

    async with SonosCloudClient(auth, app_id="com.example.voice-agent") as sonos:
        clip = await sonos.play_audio_clip(
            "RINCON_12345678901400:1",
            "http://192.168.1.50:8000/tts/response.mp3",
            name="Agent Voice",
            volume=30,
        )
        print(clip.id)


asyncio.run(main())
```

`play_audio_clip` schedules playback using the Sonos Control API's
`loadAudioClip` command and returns the clip ID needed to cancel it.

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
from sonosify import SonosCloudAuth
from sonosify.cloud.cache_handler import MemoryCacheHandler

auth = SonosCloudAuth(
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
    redirect_uri="https://agent.example.com/oauth/sonos",
    cache_handler=MemoryCacheHandler(),
)
```

The main clients, their common models and enums, and the shared
`SonosCloudError` can be imported directly from `sonosify` or `sonosify.cloud`.
Specialized cache handlers and errors remain available from their named
`sonosify.cloud` modules. Names prefixed with `_`, including endpoint URLs,
OAuth scope values, settings implementation, and cache-path selection, are
private.

`SONOSIFY_CLOUD_ACCESS_TOKEN` can replace the login/token-cache flow for
short-lived automation. The client secret is never written to the token cache
and must remain available whenever an expired token needs refreshing. Missing
configuration produces a typed `CloudConfigurationError`.

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
uv run python examples/local_audio_clip.py --volume 30  # uses SONOS_IP_ADDRESS
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

Exports are collected in `sonosify.__init__` for library consumers, including
`RepeatMode`, `NetworkError`, `SonosClient.seek`, `get_play_mode`/`set_play_mode`,
`set_shuffle`/`set_repeat`, `get_crossfade`/`set_crossfade`, and
`configure_sleep_timer`.

## Contributing

Bug reports and pull requests are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the development setup, test/lint
commands, and what CI checks on every push.

## License

MIT — see [LICENSE](LICENSE).
