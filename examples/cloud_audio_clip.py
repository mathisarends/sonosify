import argparse
import asyncio

from sonosify.cloud import SonosCloudAuth, SonosCloudClient


async def main(player: str, stream_url: str) -> None:
    auth = SonosCloudAuth.from_environment()
    async with SonosCloudClient(auth) as sonos:
        target = (
            player
            if player.startswith("RINCON_")
            else (await sonos.resolve_player(player)).id
        )
        clip = await sonos.load_audio_clip(
            target,
            stream_url,
            name="sonosify example",
        )
        print(clip.model_dump_json(by_alias=True, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("player", help="Player name or immutable player ID")
    parser.add_argument("stream_url", help="Publicly reachable MP3 or WAV URL")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.player, arguments.stream_url))
