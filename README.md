# sonosify

Programmatic Python API for discovering and controlling Sonos speakers on a local network.

This package ports the API core of `steipete/sonoscli` into Python. It intentionally does not include a CLI yet.

```python
from sonosify import SonosController

sonos = SonosController()
system = sonos.discover()

print([speaker.room_name for speaker in system.speakers])

with system.client("Kitchen") as kitchen:
    kitchen.pause()
    kitchen.set_volume(25)
    print(kitchen.now_playing())
```

Lower-level direct device access is also available:

```python
from sonosify import SonosClient

with SonosClient("192.168.1.42") as speaker:
    speaker.play_uri("https://example.com/live.mp3", radio=True, title="Example Radio")
```

Live updates use Sonos UPnP event subscriptions:

```python
from sonosify import SonosController

sonos = SonosController()
with sonos.client("Kitchen") as kitchen:
    with kitchen.watch() as watcher:
        for event in watcher:
            print(event.service, event.values)
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
