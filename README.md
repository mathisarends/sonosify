# 🔊 sonosify

![CI](https://github.com/mathisarends/sonosify/actions/workflows/ci.yaml/badge.svg)
![Python](https://img.shields.io/badge/python-3.13%20%7C%203.14-blue)
![PyPI](https://img.shields.io/pypi/v/sonosify)
![License](https://img.shields.io/badge/license-MIT-informational)

Programmatic Python API for discovering and controlling Sonos speakers on a local
network.

![sonosify banner](static/sonosify_banner.png)

An async Python API for discovery, playback, volume, queue, groups, favorites,
audio clips, and live UPnP event subscriptions.

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

### Audio clips

Audio clips use the player's local Control API WebSocket. Discovery is
required because the command targets the speaker's immutable player ID:

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
