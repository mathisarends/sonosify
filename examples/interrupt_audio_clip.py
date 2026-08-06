"""Interrupt a longer audio clip when the next turn starts.

The URL must be reachable by the Sonos player itself and should point to audio
that is long enough to still be playing when Return is pressed.

Usage:
    uv run python examples/interrupt_audio_clip.py
    uv run python examples/interrupt_audio_clip.py https://example.com/long-clip.mp3 --volume 30
"""

import argparse
import asyncio

from pydantic_settings import BaseSettings, SettingsConfigDict

from sonosify import ClipPriority, SonosClient

_DEMO_STREAM_URL = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sonos_ip_address: str
    sonos_speaker_name: str = "Sonos"


async def _main(stream_url: str, volume: int | None) -> None:
    settings = _Settings()
    print(
        f"using configured speaker: {settings.sonos_speaker_name} "
        f"({settings.sonos_ip_address})"
    )
    async with SonosClient(settings.sonos_ip_address) as speaker:
        clip = await speaker.play_audio_clip(
            stream_url,
            app_id="io.github.mathisarends.sonosify",
            name="sonosify interrupt example",
            volume=volume,
            priority=ClipPriority.HIGH,
        )
        print(f"clip scheduled: {clip.id}")
        await asyncio.to_thread(input, "press Return to start the next turn: ")
        await speaker.cancel_audio_clip(clip.id)
    print(f"clip cancelled for the next turn: {clip.id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Play a longer audio clip and interrupt it with Return."
    )
    parser.add_argument(
        "stream_url",
        nargs="?",
        default=_DEMO_STREAM_URL,
        help="HTTP(S) audio URL reachable by the Sonos player (defaults to a long demo track)",
    )
    parser.add_argument(
        "--volume",
        type=int,
        help="optional clip volume from 0 to 100; defaults to the player volume",
    )
    arguments = parser.parse_args()
    asyncio.run(_main(arguments.stream_url, arguments.volume))
