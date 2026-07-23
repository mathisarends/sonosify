"""Join a speaker to a coordinator, or remove it from its group.

Usage:
    uv run python examples/group.py join MEMBER COORDINATOR
    uv run python examples/group.py leave ROOM
    uv run python examples/group.py join Kitchen "Living Room"
"""

import asyncio
import sys

from sonosify import discover


async def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] not in {"join", "leave"}:
        raise SystemExit(
            "usage: python examples/group.py join MEMBER COORDINATOR\n"
            "       python examples/group.py leave ROOM"
        )

    action = sys.argv[1]
    system = await discover()

    if action == "join":
        member, coordinator = sys.argv[2], sys.argv[3]
        coordinator_speaker = system.find(coordinator)
        async with system.client(member, coordinator=False) as client:
            await client.join(coordinator_speaker)
    else:
        room = sys.argv[2]
        async with system.client(room, coordinator=False) as client:
            await client.unjoin()


asyncio.run(main())
