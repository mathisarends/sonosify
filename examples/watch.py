import asyncio
import sys

from sonosify import EventService, SonosController


async def main() -> None:
    room = sys.argv[1] if len(sys.argv) > 1 else None
    sonos = SonosController()

    async with await sonos.client(room) as client:
        print(f"watching {client.ip}; press Ctrl+C to stop")
        async with client.watch() as watcher:
            async for event in watcher:
                match event.service:
                    case EventService.AV_TRANSPORT:
                        print(
                            "transport",
                            event.transport_state,
                            event.track.title if event.track else "",
                        )
                    case EventService.RENDERING_CONTROL:
                        print("rendering", "volume=", event.volume, "muted=", event.muted)
                    case _:
                        print(event.service, event.values)


asyncio.run(main())
