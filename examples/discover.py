import asyncio

from sonosify import discover


async def main() -> None:
    system = await discover()
    for speaker in system.speakers:
        coordinator = "coordinator" if speaker.is_coordinator else "member"
        print(f"{speaker.room_name:24} {speaker.ip:15} {coordinator}")


asyncio.run(main())
