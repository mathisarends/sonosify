"""Duck playback for a while and then restore it.

Start music on the speaker before running this, otherwise there is nothing to
duck. The player lowers its own volume, holds it, and comes back up again.

Usage:
    uv run python examples/duck_playback.py
    uv run python examples/duck_playback.py --seconds 10
"""

import argparse
import asyncio

from pydantic_settings import BaseSettings, SettingsConfigDict

from sonosify import SonosClient


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sonos_ip_address: str
    sonos_speaker_name: str = "Sonos"


async def _main(seconds: float) -> None:
    settings = _Settings()
    print(
        f"using configured speaker: {settings.sonos_speaker_name} "
        f"({settings.sonos_ip_address})"
    )
    async with SonosClient(settings.sonos_ip_address) as speaker:
        # The duration is the player's own safety net: even if this script dies
        # before unduck, playback comes back on its own.
        await speaker.duck(int(seconds * 1000))
        print(f"ducked, holding for {seconds:g}s")
        try:
            await asyncio.sleep(seconds)
        finally:
            await speaker.unduck()
    print("unducked")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Duck the current playback, wait, then unduck."
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=10.0,
        help="how long to stay ducked, at most 60 (defaults to 10)",
    )
    arguments = parser.parse_args()
    if not 0 < arguments.seconds <= 60:
        raise SystemExit("--seconds must be greater than 0 and at most 60")
    asyncio.run(_main(arguments.seconds))
