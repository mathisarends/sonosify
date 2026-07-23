"""Read or set a speaker's volume and mute state.

Usage:
    uv run python examples/volume.py ROOM [VOLUME]
    uv run python examples/volume.py Kitchen 25
"""

import asyncio
import sys

from sonosify import SonosController


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python examples/volume.py ROOM [VOLUME]")

    room = sys.argv[1]
    sonos = SonosController()

    async with await sonos.client(room, coordinator=False) as client:
        if len(sys.argv) > 2:
            await client.set_volume(int(sys.argv[2]))

        volume = await client.get_volume()
        muted = await client.get_mute()

    print(f"volume={volume} muted={muted}")


asyncio.run(main())
