from __future__ import annotations

import asyncio
import json
import ssl
from typing import Any

import pytest

import sonosify._websocket as websocket_module
from sonosify._websocket import send_websocket_command
from sonosify.errors import LocalAPIError


class _Connection:
    def __init__(self, response: str) -> None:
        self.response = response
        self.sent = ""

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def send(self, payload: str) -> None:
        self.sent = payload

    async def recv(self) -> str:
        return self.response


def test_websocket_transport_frames_command_and_accepts_player_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection('[{"success": true}, {"id": "clip-1"}]')
    call: dict[str, Any] = {}

    def connect(uri: str, **kwargs: Any) -> _Connection:
        call["uri"] = uri
        call.update(kwargs)
        return connection

    monkeypatch.setattr(websocket_module, "connect", connect)

    result = asyncio.run(
        send_websocket_command(
            "192.168.1.10",
            {"namespace": "audioClip:1", "command": "loadAudioClip"},
            {"name": "Agent"},
            timeout=3.0,
        )
    )

    assert result == {"id": "clip-1"}
    assert call["uri"] == "wss://192.168.1.10:1443/websocket/api"
    assert call["subprotocols"] == ["v1.api.smartspeaker.audio"]
    assert call["proxy"] is None
    assert call["ssl"].verify_mode == ssl.CERT_NONE
    assert json.loads(connection.sent) == [
        {"namespace": "audioClip:1", "command": "loadAudioClip"},
        {"name": "Agent"},
    ]


def test_websocket_transport_preserves_sonos_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(
        '[{"success": false, "type": "globalError"}, '
        '{"errorCode": "ERROR_COMMAND_FAILED"}]'
    )
    monkeypatch.setattr(websocket_module, "connect", lambda *args, **kwargs: connection)

    with pytest.raises(LocalAPIError) as excinfo:
        asyncio.run(
            send_websocket_command(
                "192.168.1.10", {"command": "loadAudioClip"}, timeout=3.0
            )
        )

    assert excinfo.value.response["type"] == "globalError"
    assert excinfo.value.error_details()["sonos_code"] == "ERROR_COMMAND_FAILED"
