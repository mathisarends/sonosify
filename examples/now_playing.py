"""Show what is currently playing on a speaker.

Usage:
    uv run python examples/now_playing.py [ROOM]
"""

import asyncio
import sys

from sonosify import SonosController


async def main() -> None:
    room = sys.argv[1] if len(sys.argv) > 1 else None
    sonos = SonosController()
    async with await sonos.client(room) as client:
        state = await client.now_playing()

    print(state.state)
    if state.track:
        print(state.track.title)
        print(state.track.creator)
        print(state.track.album)


asyncio.run(main())
