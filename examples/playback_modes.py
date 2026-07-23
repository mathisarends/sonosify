"""Set shuffle, repeat, crossfade, or the sleep timer on a speaker.

Usage:
    uv run python examples/playback_modes.py ROOM shuffle on|off
    uv run python examples/playback_modes.py ROOM repeat off|one|all
    uv run python examples/playback_modes.py ROOM crossfade on|off
    uv run python examples/playback_modes.py ROOM sleep 0:30:00|off
    uv run python examples/playback_modes.py Kitchen shuffle on
"""

import asyncio
import sys

from sonosify import SonosController


async def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(
            "usage: python examples/playback_modes.py ROOM shuffle on|off\n"
            "       python examples/playback_modes.py ROOM repeat off|one|all\n"
            "       python examples/playback_modes.py ROOM crossfade on|off\n"
            "       python examples/playback_modes.py ROOM sleep 0:30:00|off"
        )

    room, setting, value = sys.argv[1], sys.argv[2], sys.argv[3]
    sonos = SonosController()

    async with await sonos.client(room) as client:
        match setting:
            case "shuffle":
                result = await client.set_shuffle(value == "on")
            case "repeat":
                result = await client.set_repeat(value)
            case "crossfade":
                await client.set_crossfade(value == "on")
                result = await client.get_crossfade()
            case "sleep":
                await client.configure_sleep_timer(None if value == "off" else value)
                result = value
            case _:
                raise SystemExit(f"unknown setting: {setting}")

    print(f"{setting} -> {result}")


asyncio.run(main())
