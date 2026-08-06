from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Mapping
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException
from websockets.protocol import State
from websockets.typing import Subprotocol

from sonosify.errors import LocalAPIError, NetworkError

# The LAN handshake requires this header but doesn't authenticate its value.
# This recognizable UUID-shaped placeholder is not a credential or secret.
_API_KEY = "123e4567-e89b-12d3-a456-426655440000"
_SUBPROTOCOL = Subprotocol("v1.api.smartspeaker.audio")
_TERMINAL_CLIP_STATES = {"DISMISSED", "DONE", "ERROR", "INTERRUPTED"}
_MAX_CACHED_CLIP_STATES = 128


class AudioClipWebSocket:
    def __init__(self, ip: str, *, timeout: float) -> None:
        self._ip = ip
        self._timeout = timeout
        self._connection: ClientConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending_response: asyncio.Future[dict[str, Any]] | None = None
        self._command_lock = asyncio.Lock()
        self._subscribed_players: set[str] = set()
        self._clip_states: dict[str, dict[str, Any]] = {}
        self._clip_waiters: dict[str, set[asyncio.Future[dict[str, Any]]]] = {}

    async def send_command(
        self,
        command: Mapping[str, Any],
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = json.dumps([dict(command), dict(options or {})])

        async with self._command_lock:
            connection = await self._open()
            loop = asyncio.get_running_loop()
            response = loop.create_future()
            self._pending_response = response
            try:
                async with asyncio.timeout(self._timeout):
                    await connection.send(payload)
                    return await response
            except (OSError, TimeoutError, WebSocketException) as exc:
                await self._discard()
                raise NetworkError(
                    f"local Sonos WebSocket request failed: {exc}"
                ) from exc
            finally:
                if self._pending_response is response:
                    self._pending_response = None

    async def subscribe_audio_clips(self, player_id: str) -> None:
        if player_id in self._subscribed_players:
            return
        await self.send_command(
            {
                "namespace": "audioClip:1",
                "command": "subscribe",
                "playerId": player_id,
            }
        )
        self._subscribed_players.add(player_id)

    async def wait_for_audio_clip(
        self, clip_id: str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        async with asyncio.timeout(timeout):
            while True:
                current = self._clip_states.get(clip_id)
                if (
                    current is not None
                    and current.get("status") in _TERMINAL_CLIP_STATES
                ):
                    return current

                waiter: asyncio.Future[dict[str, Any]] = (
                    asyncio.get_running_loop().create_future()
                )
                self._clip_waiters.setdefault(clip_id, set()).add(waiter)
                try:
                    update = await waiter
                finally:
                    waiters = self._clip_waiters.get(clip_id)
                    if waiters is not None:
                        waiters.discard(waiter)
                        if not waiters:
                            self._clip_waiters.pop(clip_id, None)
                if update.get("status") in _TERMINAL_CLIP_STATES:
                    return update

    async def close(self) -> None:
        async with self._command_lock:
            await self._discard()

    async def _open(self) -> ClientConnection:
        if self._connection is not None:
            if self._connection.state is State.OPEN:
                return self._connection
            await self._discard()

        uri = f"wss://{self._ip}:1443/websocket/api"
        ssl_context = ssl.create_default_context()
        # Players don't present certificates rooted in the host's public trust store.
        # The connection remains encrypted, but callers must trust the player on
        # the LAN.
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        try:
            connection = await connect(
                uri,
                additional_headers={"X-Sonos-Api-Key": _API_KEY},
                subprotocols=[_SUBPROTOCOL],
                compression=None,
                open_timeout=self._timeout,
                close_timeout=self._timeout,
                proxy=None,
                ssl=ssl_context,
            )
        except (OSError, TimeoutError, WebSocketException) as exc:
            raise NetworkError(
                f"local Sonos WebSocket connection failed: {exc}"
            ) from exc

        self._connection = connection
        self._reader_task = asyncio.create_task(self._read_messages(connection))
        return connection

    async def _read_messages(self, connection: ClientConnection) -> None:
        error: Exception | None = None
        try:
            while True:
                header, body = _parse_message(await connection.recv())
                if "success" in header:
                    self._resolve_response(header, body)
                else:
                    self._dispatch_event(header, body)
        except asyncio.CancelledError:
            raise
        except (OSError, WebSocketException) as exc:
            error = NetworkError(f"local Sonos WebSocket connection lost: {exc}")
        except Exception as exc:
            error = exc
        finally:
            if self._connection is connection:
                self._connection = None
                self._subscribed_players.clear()
            if error is not None:
                self._fail_pending(error)

    def _resolve_response(self, header: dict[str, Any], body: dict[str, Any]) -> None:
        response = self._pending_response
        if response is None or response.done():
            return
        if header.get("success", False):
            response.set_result(body)
        else:
            response.set_exception(LocalAPIError.from_response(header, body))

    def _dispatch_event(self, header: dict[str, Any], body: dict[str, Any]) -> None:
        if header.get("type") != "audioClipStatus":
            return
        clips = body.get("audioClips")
        if not isinstance(clips, list):
            return
        for value in clips:
            if not isinstance(value, dict) or not isinstance(value.get("id"), str):
                continue
            clip_id = value["id"]
            self._clip_states[clip_id] = value
            if len(self._clip_states) > _MAX_CACHED_CLIP_STATES:
                self._clip_states.pop(next(iter(self._clip_states)))
            for waiter in self._clip_waiters.get(clip_id, ()):
                if not waiter.done():
                    waiter.set_result(value)

    def _fail_pending(self, error: Exception) -> None:
        if self._pending_response is not None and not self._pending_response.done():
            self._pending_response.set_exception(error)
        for waiters in self._clip_waiters.values():
            for waiter in waiters:
                if not waiter.done():
                    waiter.set_exception(error)

    async def _discard(self) -> None:
        connection, self._connection = self._connection, None
        reader, self._reader_task = self._reader_task, None
        self._subscribed_players.clear()
        if reader is not None and reader is not asyncio.current_task():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if connection is not None:
            await connection.close()


def _parse_message(raw_message: str | bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        message = json.loads(raw_message)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalAPIError("player returned an invalid WebSocket response") from exc
    if (
        not isinstance(message, list)
        or len(message) != 2
        or not all(isinstance(item, dict) for item in message)
    ):
        raise LocalAPIError("player returned an invalid WebSocket response")
    return message[0], message[1]
