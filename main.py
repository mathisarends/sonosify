import asyncio

from sonosify import discover


async def main() -> None:
    system = await discover()
    for speaker in system.speakers:
        print(f"{speaker.room_name}\t{speaker.ip}")


if __name__ == "__main__":
    asyncio.run(main())
