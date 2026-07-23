"""List the current Sonos groups and their members.

Usage:
    uv run python examples/groups.py
"""

import asyncio

from sonosify import discover


async def main() -> None:
    system = await discover()
    for group in system.groups:
        coordinator = group.coordinator
        label = coordinator.room_name if coordinator else group.id
        members = ", ".join(speaker.room_name for speaker in group.members)
        print(f"{label:24} {members}")


asyncio.run(main())
