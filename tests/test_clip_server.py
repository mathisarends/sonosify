import asyncio

import httpx

from sonosify._clip_server import AudioClipServer


def test_clip_server_serves_audio_and_marks_it_fetched() -> None:
    async def run() -> tuple[bytes, str, bool]:
        server = AudioClipServer(host="127.0.0.1")
        try:
            token, fetched = server.add(b"wav-data", "audio/wav")
            async with httpx.AsyncClient() as client:
                await client.head(f"http://127.0.0.1:{server.port}/{token}")
                assert fetched.is_set() is False
                response = await client.get(f"http://127.0.0.1:{server.port}/{token}")
            await asyncio.wait_for(fetched.wait(), timeout=1.0)
            return response.content, response.headers["content-type"], fetched.is_set()
        finally:
            server.close()

    content, content_type, fetched = asyncio.run(run())

    assert content == b"wav-data"
    assert content_type == "audio/wav"
    assert fetched is True


def test_clip_server_returns_not_found_after_removal() -> None:
    async def run() -> int:
        server = AudioClipServer(host="127.0.0.1")
        try:
            token, _ = server.add(b"audio", "audio/mpeg")
            server.remove(token)
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://127.0.0.1:{server.port}/{token}")
            return response.status_code
        finally:
            server.close()

    assert asyncio.run(run()) == 404
