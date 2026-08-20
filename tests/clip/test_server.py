import asyncio

import httpx

from sonosify.clip.server import _STREAM_END, AudioClipServer


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


def test_clip_server_streams_before_body_is_complete() -> None:
    async def run() -> tuple[bytes, str, bool]:
        server = AudioClipServer(host="127.0.0.1")
        try:
            token, streamed = server.add_stream("audio/wav")

            async def read() -> tuple[bytes, str]:
                async with (
                    httpx.AsyncClient() as client,
                    client.stream(
                        "GET", f"http://127.0.0.1:{server.port}/{token}"
                    ) as response,
                ):
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                    return bytes(content), response.headers["transfer-encoding"]

            reader = asyncio.create_task(read())
            await asyncio.wait_for(streamed.requested.wait(), timeout=1.0)
            await streamed.queue.put(b"first")
            await asyncio.sleep(0)
            assert reader.done() is False
            await streamed.queue.put(b"-second")
            await streamed.queue.put(_STREAM_END)
            content, encoding = await asyncio.wait_for(reader, timeout=1.0)
            return content, encoding, streamed.requested.is_set()
        finally:
            server.close()

    content, encoding, requested = asyncio.run(run())

    assert content == b"first-second"
    assert encoding == "chunked"
    assert requested is True


def test_clip_server_rejects_a_second_stream_request() -> None:
    async def run() -> int:
        server = AudioClipServer(host="127.0.0.1")
        try:
            token, streamed = server.add_stream("audio/wav")
            first = httpx.AsyncClient()
            request = asyncio.create_task(
                first.get(f"http://127.0.0.1:{server.port}/{token}")
            )
            await asyncio.wait_for(streamed.requested.wait(), timeout=1.0)
            async with httpx.AsyncClient() as second:
                response = await second.get(f"http://127.0.0.1:{server.port}/{token}")
            await streamed.queue.put(_STREAM_END)
            await request
            await first.aclose()
            return response.status_code
        finally:
            server.close()

    assert asyncio.run(run()) == 409


def test_clip_server_close_unblocks_a_live_stream() -> None:
    async def run() -> None:
        server = AudioClipServer(host="127.0.0.1")
        token, streamed = server.add_stream("audio/wav")
        client = httpx.AsyncClient()
        request = asyncio.create_task(
            client.get(f"http://127.0.0.1:{server.port}/{token}")
        )
        await asyncio.wait_for(streamed.requested.wait(), timeout=1.0)
        await asyncio.wait_for(asyncio.to_thread(server.close), timeout=1.0)
        await asyncio.gather(request, return_exceptions=True)
        await client.aclose()

    asyncio.run(run())
