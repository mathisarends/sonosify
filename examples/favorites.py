"""List a speaker's favorites, or play one by title.

Usage:
    uv run python examples/favorites.py ROOM [TITLE]
    uv run python examples/favorites.py Kitchen "Jazz FM"
"""

import asyncio
import sys

from sonosify import SonosController


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python examples/favorites.py ROOM [TITLE]")

    room = sys.argv[1]
    query = sys.argv[2] if len(sys.argv) > 2 else None

    sonos = SonosController()
    async with await sonos.client(room) as client:
        favorites = await client.favorites()

        if query is None:
            for favorite in favorites:
                print(favorite.title)
            return

        normalized = query.casefold()
        match = next((f for f in favorites if normalized in f.title.casefold()), None)
        if match is None:
            raise SystemExit(f"no favorite matching {query!r}")

        print(f"playing {match.title}")
        await client.open_favorite(match)


asyncio.run(main())
