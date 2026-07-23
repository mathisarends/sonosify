"""Show and manage a speaker's playback queue.

Usage:
    uv run python examples/track_queue.py ROOM [add URI | clear | remove POSITION | jump POSITION]
    uv run python examples/track_queue.py Kitchen add "x-rincon-mp3radio://example.com/live.mp3"
"""

import asyncio
import sys

from sonosify import SonosController


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: python examples/track_queue.py ROOM [add URI | clear | remove POSITION | jump POSITION]"
        )

    room = sys.argv[1]
    command = sys.argv[2] if len(sys.argv) > 2 else None

    sonos = SonosController()
    async with await sonos.client(room) as client:
        match command:
            case "add":
                position = await client.enqueue_uri(sys.argv[3])
                print(f"enqueued at position {position}")
            case "clear":
                await client.clear_queue()
            case "remove":
                await client.remove_queue_item(int(sys.argv[3]))
            case "jump":
                await client.seek_queue(int(sys.argv[3]))
                await client.play()
            case None:
                pass
            case _:
                raise SystemExit(f"unknown command: {command}")

        for track in await client.queue():
            print(f"{track.position:>3} {track.title}")


asyncio.run(main())
