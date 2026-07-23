"""Stream live playback and volume events from a speaker.

Usage:
    uv run python examples/watch.py [ROOM]
"""

import asyncio
import sys

from sonosify import AVTransportEvent, RenderingControlEvent, SonosController


async def main() -> None:
    room = sys.argv[1] if len(sys.argv) > 1 else None
    sonos = SonosController()

    async with sonos.watch(room) as watcher:
        print(f"watching {watcher.ip}; press Ctrl+C to stop")
        async for event in watcher:
            match event:
                case AVTransportEvent(transport_state=state, track=track):
                    print("transport", state, track.title if track else "")
                case RenderingControlEvent(volume=volume, muted=muted):
                    print("rendering", "volume=", volume, "muted=", muted)
                case _:
                    print(event.service, event.values)


asyncio.run(main())
