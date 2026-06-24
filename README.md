# sonosify

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

from sonosify import EventService, SonosController


async def main():
    sonos = SonosController()
    async with await sonos.client("Kitchen") as kitchen:
        async with kitchen.watch() as watcher:
            async for event in watcher:
                match event.service:
                    case EventService.AV_TRANSPORT:
                        print(event.transport_state, event.track.title if event.track else "")
                    case EventService.RENDERING_CONTROL:
                        print(event.volume, event.muted)


asyncio.run(main())
```

The watch API starts a local HTTP callback server. Your OS firewall may ask whether Python can accept incoming connections.

See `examples/` for runnable scripts:

```powershell
uv run python examples/discover.py
uv run python examples/now_playing.py Kitchen
uv run python examples/watch.py Kitchen
uv run python examples/play_radio.py Kitchen https://example.com/live.mp3 "Example Radio"
uv run python examples/spotify_enqueue.py Kitchen spotify:track:6NmXV4o6bmp704aPGyTVVG
```

## Command-line interface

Install the optional CLI dependencies (Typer + Rich):

```powershell
uv pip install -e ".[cli]"
# or, from PyPI: pip install "sonosify[cli]"
```

This exposes a `sonosify` command:

```powershell
sonosify discover                       # list speakers on the network
sonosify now-playing Kitchen            # show the current track
sonosify play Kitchen                   # play / pause / stop / next / previous
sonosify volume Kitchen 25              # set volume (omit the number to read it)
sonosify mute Kitchen --on              # --on / --off, or omit to toggle
sonosify queue Kitchen                  # show the queue
sonosify favorites list Kitchen         # list favorites
sonosify favorites play Kitchen "Jazz"  # play a favorite by name
sonosify spotify Kitchen spotify:track:6NmXV4o6bmp704aPGyTVVG
sonosify watch Kitchen                  # stream live events (Ctrl+C to stop)
```

The room name is optional when only one speaker is present, and any command
accepts `--ip <address>` to target a speaker directly.

Exports are collected in `sonosify.__init__` for library consumers.
