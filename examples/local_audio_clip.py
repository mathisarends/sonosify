"""Play Sonos's built-in chime on the player configured in ``.env``.

Usage:
    uv run python examples/local_audio_clip.py
    uv run python examples/local_audio_clip.py --volume 30
"""

import argparse
import asyncio

from pydantic_settings import BaseSettings, SettingsConfigDict

from sonosify import ClipPriority, ClipType, SonosClient


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sonos_ip_address: str
    sonos_speaker_name: str = "Sonos"


async def main(volume: int | None) -> None:
    settings = _Settings()
    print(
        f"using configured speaker: {settings.sonos_speaker_name} "
        f"({settings.sonos_ip_address})"
    )
    async with SonosClient(settings.sonos_ip_address) as speaker:
        clip = await speaker.play_audio_clip(
            app_id="io.github.mathisarends.sonosify",
            name="sonosify chime example",
            volume=volume,
            priority=ClipPriority.HIGH,
            clip_type=ClipType.CHIME,
        )
    print(f"chime scheduled: {clip.id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Play a chime on SONOS_IP_ADDRESS from the environment or .env."
    )
    parser.add_argument(
        "--volume",
        type=int,
        help="optional clip volume from 0 to 100; defaults to the player volume",
    )
    arguments = parser.parse_args()
    asyncio.run(main(arguments.volume))
