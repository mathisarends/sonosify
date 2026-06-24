# sonosify

Programmatic Python API for discovering and controlling Sonos speakers on a local network.

This package ports the API core of `steipete/sonoscli` into Python. It intentionally does not include a CLI yet.

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

from sonosify import SonosController


async def main():
    sonos = SonosController()
    async with await sonos.client("Kitchen") as kitchen:
        async with kitchen.watch() as watcher:
            async for event in watcher:
                print(event.service, event.values)


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

Exports are collected in `sonosify.__init__` for library consumers.
