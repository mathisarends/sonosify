import asyncio
import sys

from sonosify import SonosController


async def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: python examples/spotify_enqueue.py ROOM SPOTIFY_URI_OR_URL")

    room = sys.argv[1]
    spotify_value = sys.argv[2]

    sonos = SonosController()
    async with await sonos.client(room) as client:
        position = await client.open_spotify(spotify_value)

    print(f"enqueued at queue position: {position}")


asyncio.run(main())
