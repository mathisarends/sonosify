import asyncio
import sys

from sonosify import SonosController


async def main() -> None:
    room = sys.argv[1] if len(sys.argv) > 1 else None
    sonos = SonosController()

    async with await sonos.client(room) as client:
        print(f"watching {client.ip}; press Ctrl+C to stop")
        async with client.watch() as watcher:
            async for event in watcher:
                if event.service == "av_transport":
                    print(
                        "transport",
                        event.transport_state,
                        event.track.title if event.track else "",
                    )
                elif event.service == "rendering_control":
                    print("rendering", "volume=", event.volume, "muted=", event.muted)
                else:
                    print(event.service, event.values)


asyncio.run(main())
