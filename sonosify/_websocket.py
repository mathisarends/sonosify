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


class AudioClipWebSocket:
    def __init__(self, ip: str, *, timeout: float) -> None:
        self._ip = ip
        self._timeout = timeout
        self._connection: ClientConnection | None = None
        self._command_lock = asyncio.Lock()

    async def send_command(
        self,
        command: Mapping[str, Any],
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = json.dumps([dict(command), dict(options or {})])

        async with self._command_lock:
            connection = await self._open()
            try:
                async with asyncio.timeout(self._timeout):
                    await connection.send(payload)
                    raw_response = await connection.recv()
            except (OSError, TimeoutError, WebSocketException) as exc:
                await self._discard()
                raise NetworkError(
                    f"local Sonos WebSocket request failed: {exc}"
                ) from exc

        return _parse_response(raw_response)

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
            self._connection = await connect(
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
        return self._connection

    async def _discard(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            await connection.close()


def _parse_response(raw_response: str | bytes) -> dict[str, Any]:
    try:
        response = json.loads(raw_response)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalAPIError("player returned an invalid WebSocket response") from exc
    if (
        not isinstance(response, list)
        or len(response) != 2
        or not all(isinstance(item, dict) for item in response)
    ):
        raise LocalAPIError("player returned an invalid WebSocket response")

    header, body = response
    if not header.get("success", False):
        raise LocalAPIError.from_response(header, body)
    return body
