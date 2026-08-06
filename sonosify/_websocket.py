from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Mapping
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from sonosify.errors import LocalAPIError, NetworkError

# The LAN handshake requires this header but doesn't authenticate its value.
# This recognizable UUID-shaped placeholder is not a credential or secret.
_API_KEY = "123e4567-e89b-12d3-a456-426655440000"
_SUBPROTOCOL = "v1.api.smartspeaker.audio"


async def send_websocket_command(
    ip: str,
    command: Mapping[str, Any],
    options: Mapping[str, Any] | None = None,
    *,
    timeout: float,
) -> dict[str, Any]:
    uri = f"wss://{ip}:1443/websocket/api"
    ssl_context = ssl.create_default_context()
    # Players don't present certificates rooted in the host's public trust store.
    # The connection remains encrypted, but callers must trust the player on the LAN.
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    payload = json.dumps([dict(command), dict(options or {})])

    try:
        async with connect(
            uri,
            additional_headers={"X-Sonos-Api-Key": _API_KEY},
            subprotocols=[_SUBPROTOCOL],
            compression=None,
            open_timeout=timeout,
            close_timeout=timeout,
            proxy=None,
            ssl=ssl_context,
        ) as websocket:
            async with asyncio.timeout(timeout):
                await websocket.send(payload)
                raw_response = await websocket.recv()
    except (OSError, TimeoutError, WebSocketException) as exc:
        raise NetworkError(f"local Sonos WebSocket request failed: {exc}") from exc

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
