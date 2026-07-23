import asyncio
import json

import httpx
import pytest

from sonosify.cloud import (
    ClipPriority,
    ClipType,
    CloudAPIError,
    CloudConfigurationError,
    SonosCloudAuth,
    SonosCloudClient,
)


def _auth() -> SonosCloudAuth:
    return SonosCloudAuth(access_token="test-token")


def test_households_and_topology_are_typed() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/households"):
            return httpx.Response(200, json={"households": [{"id": "Sonos_123"}]})
        return httpx.Response(
            200,
            json={
                "groups": [
                    {
                        "id": "RINCON_group:1",
                        "name": "Kitchen",
                        "coordinatorId": "RINCON_player",
                        "playerIds": ["RINCON_player"],
                        "playbackState": "PLAYBACK_STATE_PLAYING",
                    }
                ],
                "players": [
                    {
                        "id": "RINCON_player",
                        "name": "Kitchen",
                        "capabilities": ["PLAYBACK", "AUDIO_CLIP"],
                    }
                ],
            },
        )

    async def run() -> None:
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
            SonosCloudClient(_auth(), http_client=http) as client,
        ):
            households = await client.get_households()
            topology = await client.get_groups(households[0].id)

        assert households[0].id == "Sonos_123"
        assert topology.groups[0].coordinator_id == "RINCON_player"
        assert topology.players[0].capabilities == ("PLAYBACK", "AUDIO_CLIP")

    asyncio.run(run())

    assert requests[0].headers["Authorization"] == "Bearer test-token"
    assert requests[0].url.params["connectedOnly"] == "true"
    assert requests[1].url.path.endswith("/households/Sonos_123/groups")


def test_load_audio_clip_builds_documented_payload() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "clip-1",
                "name": "Agent",
                "appId": "com.example.agent",
                "priority": "HIGH",
                "clipType": "VOICE_ASSISTANT",
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SonosCloudClient(
                _auth(),
                app_id="com.example.agent",
                http_client=http,
            )
            clip = await client.load_audio_clip(
                "RINCON_123:1",
                "https://media.example.test/voice.mp3",
                name="Agent",
                volume=30,
                priority=ClipPriority.HIGH,
                clip_type=ClipType.VOICE_ASSISTANT,
            )
            assert clip.id == "clip-1"

    asyncio.run(run())

    assert str(seen["path"]).endswith("/players/RINCON_123:1/audioClip")
    assert seen["json"] == {
        "name": "Agent",
        "appId": "com.example.agent",
        "priority": "HIGH",
        "clipLEDBehavior": "NONE",
        "streamUrl": "https://media.example.test/voice.mp3",
        "volume": 30,
        "clipType": "VOICE_ASSISTANT",
    }


def test_audio_clip_requires_app_id_and_valid_url() -> None:
    async def run() -> None:
        async with SonosCloudClient(_auth()) as client:
            with pytest.raises(CloudConfigurationError):
                await client.load_audio_clip("player", "https://example.test/a.mp3")

    asyncio.run(run())


def test_control_api_error_preserves_status_and_sonos_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(499, json={"errorCode": "ERROR_NO_CONTENT"})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SonosCloudClient(_auth(), http_client=http)
            with pytest.raises(CloudAPIError) as excinfo:
                await client.play("RINCON_group:1")

        assert excinfo.value.status_code == 499
        assert excinfo.value.error_code == "ERROR_NO_CONTENT"
        assert excinfo.value.error_details()["sonos_code"] == "ERROR_NO_CONTENT"

    asyncio.run(run())
