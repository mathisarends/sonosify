from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Mapping
from typing import Any

import pytest
from websockets.protocol import State

import sonosify._websocket as websocket_module
from sonosify._websocket import AudioClipWebSocket
from sonosify.errors import LocalAPIError, NetworkError


class _Connection:
    def __init__(self, *responses: str, send_error: Exception | None = None) -> None:
        self._responses = list(responses)
        self._incoming: asyncio.Queue[str] = asyncio.Queue()
        self._send_error = send_error
        self._awaiting_response = False
        self.state = State.OPEN
        self.sent: list[str] = []
        self.close_calls = 0

    async def send(self, payload: str) -> None:
        if self._send_error is not None:
            raise self._send_error
        if self._awaiting_response:
            raise AssertionError("commands were sent concurrently")
        self._awaiting_response = True
        self.sent.append(payload)
        self._incoming.put_nowait(self._responses.pop(0))

    async def recv(self) -> str:
        response = await self._incoming.get()
        self._awaiting_response = False
        return response

    def emit(self, message: str) -> None:
        self._incoming.put_nowait(message)

    async def close(self) -> None:
        self.close_calls += 1
        self.state = State.CLOSED


def test_websocket_transport_reuses_connection_and_accepts_player_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(
        '[{"success": true}, {"id": "clip-1"}]',
        '[{"success": true}, {}]',
    )
    calls: list[dict[str, Any]] = []

    async def connect(uri: str, **kwargs: Any) -> _Connection:
        calls.append({"uri": uri, **kwargs})
        return connection

    monkeypatch.setattr(websocket_module, "connect", connect)

    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        transport = AudioClipWebSocket("192.168.1.10", timeout=3.0)
        first, second = await asyncio.gather(
            transport.send_command(
                {"namespace": "audioClip:1", "command": "loadAudioClip"},
                {"name": "Agent"},
            ),
            transport.send_command(
                {"namespace": "audioClip:1", "command": "cancelAudioClip"},
                {"clipId": "clip-1"},
            ),
        )
        await transport.close()
        return first, second

    first, second = asyncio.run(run())

    assert first == {"id": "clip-1"}
    assert second == {}
    assert len(calls) == 1
    assert calls[0]["uri"] == "wss://192.168.1.10:1443/websocket/api"
    assert calls[0]["subprotocols"] == ["v1.api.smartspeaker.audio"]
    assert calls[0]["proxy"] is None
    assert calls[0]["ssl"].verify_mode == ssl.CERT_NONE
    assert [json.loads(payload) for payload in connection.sent] == [
        [
            {"namespace": "audioClip:1", "command": "loadAudioClip"},
            {"name": "Agent"},
        ],
        [
            {"namespace": "audioClip:1", "command": "cancelAudioClip"},
            {"clipId": "clip-1"},
        ],
    ]
    assert connection.close_calls == 1


def test_websocket_transport_reconnects_when_player_closed_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _Connection('[{"success": true}, {"id": "clip-1"}]')
    second = _Connection('[{"success": true}, {}]')
    connections = iter((first, second))
    connect_calls = 0

    async def connect(*args: object, **kwargs: object) -> _Connection:
        nonlocal connect_calls
        connect_calls += 1
        return next(connections)

    monkeypatch.setattr(websocket_module, "connect", connect)

    async def run() -> None:
        transport = AudioClipWebSocket("192.168.1.10", timeout=3.0)
        await transport.send_command({"command": "loadAudioClip"})
        first.state = State.CLOSED
        await transport.send_command({"command": "cancelAudioClip"})
        await transport.close()

    asyncio.run(run())

    assert connect_calls == 2
    assert first.close_calls == 1
    assert second.close_calls == 1


def test_websocket_transport_discards_failed_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = _Connection(send_error=OSError("connection lost"))
    recovered = _Connection('[{"success": true}, {}]')
    connections = iter((failed, recovered))

    async def connect(*args: object, **kwargs: object) -> _Connection:
        return next(connections)

    monkeypatch.setattr(websocket_module, "connect", connect)

    async def run() -> None:
        transport = AudioClipWebSocket("192.168.1.10", timeout=3.0)
        with pytest.raises(NetworkError, match="request failed"):
            await transport.send_command({"command": "loadAudioClip"})
        await transport.send_command({"command": "cancelAudioClip"})
        await transport.close()

    asyncio.run(run())

    assert failed.close_calls == 1
    assert recovered.close_calls == 1


def test_websocket_transport_wraps_connect_failure_as_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def connect(*args: object, **kwargs: object) -> _Connection:
        raise OSError("no route to host")

    monkeypatch.setattr(websocket_module, "connect", connect)

    async def run() -> None:
        transport = AudioClipWebSocket("192.168.1.10", timeout=3.0)
        with pytest.raises(NetworkError, match="connection failed"):
            await transport.send_command({"command": "loadAudioClip"})

    asyncio.run(run())


def test_websocket_transport_rejects_invalid_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection("not json")

    async def connect(*args: object, **kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(websocket_module, "connect", connect)

    async def run() -> None:
        transport = AudioClipWebSocket("192.168.1.10", timeout=3.0)
        with pytest.raises(LocalAPIError, match="invalid WebSocket response"):
            await transport.send_command({"command": "loadAudioClip"})
        await transport.close()

    asyncio.run(run())


def test_websocket_transport_rejects_malformed_response_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection('{"success": true}')

    async def connect(*args: object, **kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(websocket_module, "connect", connect)

    async def run() -> None:
        transport = AudioClipWebSocket("192.168.1.10", timeout=3.0)
        with pytest.raises(LocalAPIError, match="invalid WebSocket response"):
            await transport.send_command({"command": "loadAudioClip"})
        await transport.close()

    asyncio.run(run())


def test_websocket_transport_preserves_sonos_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(
        '[{"success": false, "type": "globalError"}, '
        '{"errorCode": "ERROR_COMMAND_FAILED"}]'
    )

    async def connect(*args: object, **kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(websocket_module, "connect", connect)

    async def run() -> None:
        transport = AudioClipWebSocket("192.168.1.10", timeout=3.0)
        with pytest.raises(LocalAPIError) as excinfo:
            await transport.send_command({"command": "loadAudioClip"})
        await transport.close()
        assert excinfo.value.response["type"] == "globalError"
        assert excinfo.value.error_details()["sonos_code"] == "ERROR_COMMAND_FAILED"

    asyncio.run(run())


def test_websocket_transport_routes_audio_clip_status_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(
        '[{"success": true}, {}]',
        '[{"success": true}, {"id": "clip-1"}]',
    )

    async def connect(*args: object, **kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(websocket_module, "connect", connect)

    async def run() -> Mapping[str, Any]:
        transport = AudioClipWebSocket("192.168.1.10", timeout=3.0)
        await transport.subscribe_audio_clips("RINCON_1")
        await transport.send_command({"command": "loadAudioClip"})
        connection.emit(
            '[{"namespace": "audioClip:1", "type": "audioClipStatus"}, '
            '{"audioClips": [{"id": "clip-1", "name": "Agent", '
            '"appId": "com.example.agent", "status": "DONE"}]}]'
        )
        result = await transport.wait_for_audio_clip("clip-1", timeout=1.0)
        await transport.close()
        return result

    result = asyncio.run(run())

    assert result["status"] == "DONE"
    assert json.loads(connection.sent[0])[0]["command"] == "subscribe"


def test_websocket_transport_subscribes_to_audio_clips_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection('[{"success": true}, {}]')

    async def connect(*args: object, **kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(websocket_module, "connect", connect)

    async def run() -> None:
        transport = AudioClipWebSocket("192.168.1.10", timeout=3.0)
        await transport.subscribe_audio_clips("RINCON_1")
        await transport.subscribe_audio_clips("RINCON_1")
        await transport.close()

    asyncio.run(run())

    assert len(connection.sent) == 1


def test_websocket_transport_accepts_event_before_command_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection('[{"success": true}, {"id": "clip-1"}]')
    connection.emit(
        '[{"namespace": "audioClip:1", "type": "audioClipStatus"}, '
        '{"audioClips": [{"id": "clip-1", "name": "Agent", '
        '"appId": "com.example.agent", "status": "DONE"}]}]'
    )

    async def connect(*args: object, **kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(websocket_module, "connect", connect)

    async def run() -> tuple[dict[str, Any], Mapping[str, Any]]:
        transport = AudioClipWebSocket("192.168.1.10", timeout=3.0)
        response = await transport.send_command({"command": "loadAudioClip"})
        event = await transport.wait_for_audio_clip("clip-1", timeout=1.0)
        await transport.close()
        return response, event

    response, event = asyncio.run(run())

    assert response == {"id": "clip-1"}
    assert event["status"] == "DONE"
