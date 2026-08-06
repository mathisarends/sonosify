"""Host and play a local WAV or MP3 file as a Sonos audio clip.

Usage:
    uv run python examples/play_audio_clip_data.py path/to/response.wav
    uv run python examples/play_audio_clip_data.py path/to/response.mp3 --volume 30
"""

import argparse
import asyncio
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from sonosify import ClipPriority, ClipStatus, SonosClient


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sonos_ip_address: str


def _content_type(path: Path) -> str:
    match path.suffix.lower():
        case ".wav":
            return "audio/wav"
        case ".mp3":
            return "audio/mpeg"
        case suffix:
            raise ValueError(f"unsupported audio file extension: {suffix or '<none>'}")


async def main(path: Path, volume: int | None) -> None:
    settings = _Settings()
    audio = path.read_bytes()

    async with SonosClient(settings.sonos_ip_address) as speaker:
        handle = await speaker.play_audio_clip_data(
            audio,
            content_type=_content_type(path),
            app_id="io.github.mathisarends.sonosify",
            name=path.name,
            volume=volume,
            priority=ClipPriority.HIGH,
        )
        print(f"clip scheduled: {handle.id}")

        await handle.wait_until_fetched(timeout=10)
        print("audio fetched by player")

        clip = await handle.wait_until_finished(timeout=120)
        print(f"playback finished with status: {clip.status}")
        if clip.status is not ClipStatus.DONE:
            raise RuntimeError(f"audio clip did not complete: {clip.status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Play a local WAV or MP3 file as a Sonos audio clip."
    )
    parser.add_argument("path", type=Path, help="path to a WAV or MP3 file")
    parser.add_argument(
        "--volume",
        type=int,
        help="optional clip volume from 0 to 100; defaults to the player volume",
    )
    arguments = parser.parse_args()
    asyncio.run(main(arguments.path, arguments.volume))
