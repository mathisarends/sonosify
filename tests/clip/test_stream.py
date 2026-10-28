import asyncio

import pytest

from sonosify import AudioClip, AudioClipStream, ClipStatus
from sonosify.clip.server import AudioClipServer
from sonosify.errors import NetworkError


class _WebSocket:
    async def wait_for_audio_clip(
        self, clip_id: str, *, timeout: float | None = None
    ) -> dict[str, object]:
        return {
            "id": clip_id,
            "name": "test",
            "appId": "test",
            "status": "DONE",
        }


def _clip() -> AudioClip:
    return AudioClip(id="clip-1", name="test", app_id="test")


def test_stream_defers_load_until_prebuffer_threshold() -> None:
    async def run() -> tuple[list[str], bytes, ClipStatus | None]:
        server = AudioClipServer(host="127.0.0.1")
        loads: list[str] = []

        async def load() -> AudioClip:
            loads.append("load")
            return _clip()

        async def cancel(clip_id: str) -> None:
            raise AssertionError(f"unexpected cancellation of {clip_id}")

        try:
            token, streamed = server.add_stream("audio/wav")
            handle = AudioClipStream(
                streamed=streamed,
                server=server,
                token=token,
                websocket=_WebSocket(),  # type: ignore[arg-type]
                load=load,
                cancel=cancel,
                prebuffer_bytes=6,
            )
            await handle.write(b"abc")
            assert loads == []
            await handle.write(b"def")
            assert loads == ["load"]
            queued = await streamed.queue.get()
            await handle.end()
            finished = await handle.wait_until_finished(timeout=1.0)
            return loads, queued, finished.status
        finally:
            server.close()

    loads, queued, status = asyncio.run(run())

    assert loads == ["load"]
    assert queued == b"abc"
    assert status is ClipStatus.DONE


def test_stream_queue_applies_backpressure() -> None:
    async def run() -> None:
        server = AudioClipServer(host="127.0.0.1")

        async def load() -> AudioClip:
            return _clip()

        async def cancel(clip_id: str) -> None:
            pass

        try:
            token, streamed = server.add_stream("audio/wav")
            handle = AudioClipStream(
                streamed=streamed,
                server=server,
                token=token,
                websocket=_WebSocket(),  # type: ignore[arg-type]
                load=load,
                cancel=cancel,
                prebuffer_bytes=0,
            )
            await handle.write(b"start")
            while not streamed.queue.full():
                await handle.write(b"chunk")
            blocked = asyncio.create_task(handle.write(b"blocked"))
            await asyncio.sleep(0.01)
            assert blocked.done() is False
            await streamed.queue.get()
            await asyncio.wait_for(blocked, timeout=1.0)
            await handle.abort()
        finally:
            server.close()

    asyncio.run(run())


def test_stream_abort_is_idempotent_before_and_after_load() -> None:
    async def run(write_first: bool) -> list[str]:
        server = AudioClipServer(host="127.0.0.1")
        cancellations: list[str] = []

        async def load() -> AudioClip:
            return _clip()

        async def cancel(clip_id: str) -> None:
            cancellations.append(clip_id)

        try:
            token, streamed = server.add_stream("audio/wav")
            handle = AudioClipStream(
                streamed=streamed,
                server=server,
                token=token,
                websocket=_WebSocket(),  # type: ignore[arg-type]
                load=load,
                cancel=cancel,
                prebuffer_bytes=10,
            )
            if write_first:
                await handle.write(b"0123456789")
            await handle.abort()
            await handle.abort()
            with pytest.raises(RuntimeError, match="aborted"):
                await handle.write(b"later")
            return cancellations
        finally:
            server.close()

    assert asyncio.run(run(False)) == []
    assert asyncio.run(run(True)) == ["clip-1"]


def test_stream_rejects_empty_end() -> None:
    async def run() -> None:
        server = AudioClipServer(host="127.0.0.1")
        try:
            token, streamed = server.add_stream("audio/wav")
            handle = AudioClipStream(
                streamed=streamed,
                server=server,
                token=token,
                websocket=_WebSocket(),  # type: ignore[arg-type]
                load=lambda: asyncio.sleep(0, result=_clip()),
                cancel=lambda clip_id: asyncio.sleep(0),
                prebuffer_bytes=0,
            )
            with pytest.raises(ValueError, match="must not be empty"):
                await handle.end()
            handle.close()
        finally:
            server.close()

    asyncio.run(run())


def test_stream_write_fails_after_player_disconnect() -> None:
    async def run() -> None:
        server = AudioClipServer(host="127.0.0.1")
        try:
            token, streamed = server.add_stream("audio/wav")
            handle = AudioClipStream(
                streamed=streamed,
                server=server,
                token=token,
                websocket=_WebSocket(),  # type: ignore[arg-type]
                load=lambda: asyncio.sleep(0, result=_clip()),
                cancel=lambda clip_id: asyncio.sleep(0),
                prebuffer_bytes=0,
            )
            streamed.disconnected.set()
            streamed.unavailable.set()
            with pytest.raises(NetworkError, match="disconnected"):
                await handle.write(b"audio")
            handle.close()
        finally:
            server.close()

    asyncio.run(run())


def test_stream_close_rejects_later_writes() -> None:
    async def run() -> None:
        server = AudioClipServer(host="127.0.0.1")
        try:
            token, streamed = server.add_stream("audio/wav")
            handle = AudioClipStream(
                streamed=streamed,
                server=server,
                token=token,
                websocket=_WebSocket(),  # type: ignore[arg-type]
                load=lambda: asyncio.sleep(0, result=_clip()),
                cancel=lambda clip_id: asyncio.sleep(0),
                prebuffer_bytes=100,
            )
            handle.close()
            with pytest.raises(RuntimeError, match="closed"):
                await handle.write(b"audio")
        finally:
            server.close()

    asyncio.run(run())


@pytest.mark.parametrize("prebuffer_bytes", [0, 33])
def test_abort_unblocks_a_writer_with_a_full_buffer(prebuffer_bytes: int) -> None:
    async def run() -> None:
        server = AudioClipServer(host="127.0.0.1")
        cancellations: list[str] = []

        async def cancel(clip_id: str) -> None:
            cancellations.append(clip_id)

        token, streamed = server.add_stream("audio/wav")
        handle = AudioClipStream(
            streamed=streamed,
            server=server,
            token=token,
            websocket=_WebSocket(),  # type: ignore[arg-type]
            load=lambda: asyncio.sleep(0, result=_clip()),
            cancel=cancel,
            prebuffer_bytes=prebuffer_bytes,
        )
        writer: asyncio.Task[None] | None = None
        try:
            for _ in range(streamed.queue.maxsize):
                await handle.write(b"a")
            writer = asyncio.create_task(handle.write(b"b"))
            await asyncio.sleep(0)
            assert not writer.done()

            await asyncio.wait_for(handle.abort(), timeout=1.0)
            with pytest.raises(NetworkError, match="closed"):
                await asyncio.wait_for(writer, timeout=1.0)
            assert streamed.closed.is_set()
            assert cancellations == ["clip-1"]
        finally:
            handle.close()
            if writer is not None:
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
            server.close()

    asyncio.run(run())


@pytest.mark.parametrize("ending", [False, True])
def test_cancelled_write_or_end_cleans_up_pending_queue_tasks(ending: bool) -> None:
    async def run() -> None:
        server = AudioClipServer(host="127.0.0.1")
        token, streamed = server.add_stream("audio/wav")
        handle = AudioClipStream(
            streamed=streamed,
            server=server,
            token=token,
            websocket=_WebSocket(),  # type: ignore[arg-type]
            load=lambda: asyncio.sleep(0, result=_clip()),
            cancel=lambda clip_id: asyncio.sleep(0),
            prebuffer_bytes=0,
        )
        writer: asyncio.Task[None] | None = None
        try:
            for _ in range(streamed.queue.maxsize):
                await handle.write(b"buffered")
            previous_tasks = asyncio.all_tasks()
            writer = asyncio.create_task(
                handle.end() if ending else handle.write(b"cancelled")
            )
            await asyncio.sleep(0)
            assert not writer.done()
            writer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await writer

            assert asyncio.all_tasks() == previous_tasks
            buffered = [
                streamed.queue.get_nowait() for _ in range(streamed.queue.qsize())
            ]
            assert buffered == [b"buffered"] * streamed.queue.maxsize
            await asyncio.sleep(0)
            assert streamed.queue.empty()
            await handle.write(b"after cancellation")
            assert streamed.queue.get_nowait() == b"after cancellation"
        finally:
            handle.close()
            if writer is not None:
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
            server.close()

    asyncio.run(run())
