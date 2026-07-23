"""Resume (or start) playback on a paused speaker.

Usage:
    uv run python examples/resume_playback.py [ROOM]
"""

import asyncio
import sys

from sonosify import SonosController


async def main() -> None:
    room = sys.argv[1] if len(sys.argv) > 1 else None
    sonos = SonosController()

    async with await sonos.client(room) as client:
        before = await client.get_transport_info()
        await client.play()
        after = await client.now_playing()

    print(f"{before.state} -> {after.state}")
    if after.track:
        print(after.track.title)


asyncio.run(main())
