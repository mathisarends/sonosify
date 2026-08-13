"""Stream live playback and volume events from a speaker.

Usage:
    uv run python examples/watch.py [ROOM]
"""

import asyncio
import sys

from sonosify import (
    ALL_SERVICES,
    AVTransportEvent,
    GroupRenderingControlEvent,
    QueueEvent,
    RenderingControlEvent,
    SonosController,
    SonosEvent,
    SubscriptionLost,
    SubscriptionRestored,
    ZoneGroupTopologyEvent,
)


async def main() -> None:
    room = sys.argv[1] if len(sys.argv) > 1 else None
    sonos = SonosController()

    async with sonos.watch(room, services=ALL_SERVICES) as watcher:

        @watcher.on(AVTransportEvent)
        def transport(event: AVTransportEvent) -> None:
            title = event.track.title if event.track else ""
            print("transport", event.transport_state, event.play_mode, title)

        @watcher.on(RenderingControlEvent, GroupRenderingControlEvent)
        def rendering(event: SonosEvent) -> None:
            print("rendering", event.model_dump(exclude={"values"}, exclude_none=True))

        @watcher.on(QueueEvent, ZoneGroupTopologyEvent)
        async def topology(event: SonosEvent) -> None:
            print(event.service, "changed")

        @watcher.on(SubscriptionLost)
        def lost(event: SubscriptionLost) -> None:
            print("lost", ", ".join(event.affected_services), event.error)

        @watcher.on(SubscriptionRestored)
        def restored(event: SubscriptionRestored) -> None:
            print("restored", ", ".join(event.affected_services))

        @watcher.on()
        def everything(event: SonosEvent) -> None:
            print(" ", event.service, sorted(event.values))

        subscribed = ", ".join(watcher.subscribed_services)
        print(f"watching {watcher.ip} [{subscribed}]; press Ctrl+C to stop")
        await watcher.run()


asyncio.run(main())
