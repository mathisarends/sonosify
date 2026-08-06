import asyncio

import httpx
import pytest

import sonosify.client as client_module
from sonosify import ClipStatus, Favorite, Speaker
from sonosify.client import PositionInfo, SonosClient, TransportInfo
from sonosify.errors import LocalAPIError, NetworkError
from sonosify.events import EventSubscription


class _RecordingSoap:
    def __init__(self, responses: dict[str, dict[str, str]] | None = None) -> None:
        self.calls: list[tuple[str, str, str, dict[str, object]]] = []
        self._responses = responses or {}

    async def __call__(
        self,
        http: httpx.AsyncClient,
        endpoint_url: str,
        service_urn: str,
        action: str,
        args: dict[str, object],
    ) -> dict[str, str]:
        self.calls.append((endpoint_url, service_urn, action, dict(args)))
        return self._responses.get(action, {})


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _RecordingSoap:
    recorder = _RecordingSoap()
    monkeypatch.setattr(client_module, "soap_call", recorder)
    return recorder


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def test_from_speaker_copies_connection_details() -> None:
    speaker = Speaker(ip="192.168.1.10", room_name="Kitchen", uid="RINCON_1", port=1401)

    client = SonosClient.from_speaker(speaker, timeout=5.0)

    assert client.ip == "192.168.1.10"
    assert client.port == 1401
    assert client.uid == "RINCON_1"
    assert client.base_url == "http://192.168.1.10:1401"


def test_context_manager_closes_owned_http_client() -> None:
    async def run() -> bool:
        async with SonosClient("192.168.1.10") as client:
            http = client._http  # noqa: SLF001 - inspecting internal for close behavior
        return http.is_closed

    assert _run(run()) is True


def test_close_closes_local_control_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_calls = 0

    async def close(self: object) -> None:
        nonlocal close_calls
        close_calls += 1

    monkeypatch.setattr(client_module._websocket.AudioClipWebSocket, "close", close)

    async def run() -> None:
        client = SonosClient("192.168.1.10")
        await client.close()

    asyncio.run(run())

    assert close_calls == 1


def test_play_audio_clip_sends_local_control_api_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    async def send_command(
        self: object, *args: object, **kwargs: object
    ) -> dict[str, object]:
        calls.append((*args, kwargs))
        return {
            "id": "clip-1",
            "name": "Agent",
            "appId": "com.example.agent",
            "priority": "HIGH",
            "clipType": "VOICE_ASSISTANT",
        }

    monkeypatch.setattr(
        client_module._websocket.AudioClipWebSocket, "send_command", send_command
    )
    client = SonosClient("192.168.1.10", uid="RINCON_1", timeout=4.0)

    clip = _run(
        client.play_audio_clip(
            "http://192.168.1.20/voice.mp3",
            app_id="com.example.agent",
            name="Agent",
            volume=30,
            priority=client_module.ClipPriority.HIGH,
            clip_type=client_module.ClipType.VOICE_ASSISTANT,
        )
    )

    assert clip.id == "clip-1"
    assert calls == [
        (
            {
                "namespace": "audioClip:1",
                "command": "loadAudioClip",
                "playerId": "RINCON_1",
            },
            {
                "name": "Agent",
                "appId": "com.example.agent",
                "priority": "HIGH",
                "clipLEDBehavior": "NONE",
                "streamUrl": "http://192.168.1.20/voice.mp3",
                "volume": 30,
                "clipType": "VOICE_ASSISTANT",
            },
            {},
        )
    ]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"name": ""}, "audio clip name"),
        ({"app_id": ""}, "app_id"),
        ({"volume": 101}, "audio clip volume"),
        ({"stream_url": "not-a-url"}, "stream_url must be an absolute"),
        ({"http_authorization": "x" * 513}, "http_authorization"),
    ],
)
def test_play_audio_clip_validates_arguments(
    kwargs: dict[str, object], match: str
) -> None:
    client = SonosClient("192.168.1.10")
    base_kwargs: dict[str, object] = {"app_id": "com.example.agent", "name": "Agent"}
    base_kwargs.update(kwargs)

    with pytest.raises(ValueError, match=match):
        _run(client.play_audio_clip(**base_kwargs))


def test_play_audio_clip_includes_http_authorization_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    async def send_command(
        self: object, *args: object, **kwargs: object
    ) -> dict[str, object]:
        calls.append((*args, kwargs))
        return {"id": "clip-1", "name": "Agent", "appId": "com.example.agent"}

    monkeypatch.setattr(
        client_module._websocket.AudioClipWebSocket, "send_command", send_command
    )
    client = SonosClient("192.168.1.10", uid="RINCON_1")

    _run(
        client.play_audio_clip(
            app_id="com.example.agent", name="Agent", http_authorization="Bearer x"
        )
    )

    assert calls[0][1]["httpAuthorization"] == "Bearer x"


def test_play_audio_clip_data_hosts_audio_and_waits_for_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeServer:
        port = 4321

        def __init__(self) -> None:
            self.fetched = asyncio.Event()
            self.fetched.set()
            self.added: list[tuple[bytes, str]] = []
            self.removed: list[str] = []

        def add(self, audio: bytes, content_type: str) -> tuple[str, asyncio.Event]:
            self.added.append((audio, content_type))
            return "token.wav", self.fetched

        def remove(self, token: str) -> None:
            self.removed.append(token)

        def close(self) -> None:
            pass

    subscriptions: list[str] = []
    commands: list[tuple[object, object]] = []

    async def subscribe(self: object, player_id: str) -> None:
        subscriptions.append(player_id)

    async def send_command(
        self: object, command: object, options: object
    ) -> dict[str, object]:
        commands.append((command, options))
        return {
            "id": "clip-1",
            "name": "Agent",
            "appId": "com.example.agent",
        }

    async def wait_for_audio_clip(
        self: object, clip_id: str, *, timeout: float | None = None
    ) -> dict[str, object]:
        return {
            "id": clip_id,
            "name": "Agent",
            "appId": "com.example.agent",
            "status": "DONE",
        }

    server = FakeServer()
    monkeypatch.setattr(client_module, "AudioClipServer", lambda: server)
    monkeypatch.setattr(client_module, "_local_ip_for", lambda ip: "192.168.1.20")
    monkeypatch.setattr(
        client_module._websocket.AudioClipWebSocket,
        "subscribe_audio_clips",
        subscribe,
    )
    monkeypatch.setattr(
        client_module._websocket.AudioClipWebSocket, "send_command", send_command
    )
    monkeypatch.setattr(
        client_module._websocket.AudioClipWebSocket,
        "wait_for_audio_clip",
        wait_for_audio_clip,
    )

    async def run() -> tuple[bool, ClipStatus | None]:
        client = SonosClient("192.168.1.10", uid="RINCON_1")
        handle = await client.play_audio_clip_data(
            b"wav-data",
            app_id="com.example.agent",
            name="Agent",
        )
        await handle.wait_until_fetched(timeout=1.0)
        finished = await handle.wait_until_finished(timeout=1.0)
        return handle.fetched, finished.status

    fetched, status = asyncio.run(run())

    assert fetched is True
    assert status is ClipStatus.DONE
    assert subscriptions == ["RINCON_1"]
    assert server.added == [(b"wav-data", "audio/wav")]
    assert server.removed == ["token.wav"]
    assert commands[0][1]["streamUrl"] == ("http://192.168.1.20:4321/token.wav")


@pytest.mark.parametrize(
    ("audio", "content_type", "match"),
    [
        (b"", "audio/wav", "must not be empty"),
        (b"audio", "audio/ogg", "content_type"),
    ],
)
def test_play_audio_clip_data_validates_local_media(
    audio: bytes, content_type: str, match: str
) -> None:
    client = SonosClient("192.168.1.10", uid="RINCON_1")

    with pytest.raises(ValueError, match=match):
        _run(
            client.play_audio_clip_data(
                audio,
                content_type=content_type,
                app_id="com.example.agent",
            )
        )


def test_cancel_audio_clip_rejects_empty_clip_id() -> None:
    client = SonosClient("192.168.1.10", uid="RINCON_1")

    with pytest.raises(ValueError, match="clip_id must not be empty"):
        _run(client.cancel_audio_clip(""))


def test_player_id_wraps_http_errors_as_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SonosClient("192.168.1.10", http_client=http)
            with pytest.raises(NetworkError, match="cannot read Sonos device identity"):
                await client.cancel_audio_clip("clip-1")

    asyncio.run(run())


def test_player_id_wraps_unparseable_xml_as_local_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not xml")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SonosClient("192.168.1.10", http_client=http)
            with pytest.raises(LocalAPIError, match="invalid device metadata"):
                await client.cancel_audio_clip("clip-1")

    asyncio.run(run())


def test_player_id_raises_when_udn_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                '<root xmlns="urn:schemas-upnp-org:device-1-0"><device></device></root>'
            ),
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SonosClient("192.168.1.10", http_client=http)
            with pytest.raises(LocalAPIError, match="contains no UDN"):
                await client.cancel_audio_clip("clip-1")

    asyncio.run(run())


def test_transport_info_coerces_non_string_state_to_none() -> None:
    info = TransportInfo.model_validate({"CurrentTransportState": None})

    assert info.state is None


def test_cancel_audio_clip_sends_clip_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []

    async def send_command(
        self: object, *args: object, **kwargs: object
    ) -> dict[str, object]:
        calls.append((*args, kwargs))
        return {}

    monkeypatch.setattr(
        client_module._websocket.AudioClipWebSocket, "send_command", send_command
    )
    client = SonosClient("192.168.1.10", uid="RINCON_1")

    _run(client.cancel_audio_clip("clip-1"))

    assert calls[0][0] == {
        "namespace": "audioClip:1",
        "command": "cancelAudioClip",
        "playerId": "RINCON_1",
    }
    assert calls[0][1] == {"id": "clip-1"}


def test_local_audio_clip_resolves_player_id_from_configured_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xml/device_description.xml"
        return httpx.Response(
            200,
            text=(
                '<root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
                "<UDN>uuid:RINCON_DIRECT</UDN>"
                "</device></root>"
            ),
        )

    async def send_command(
        self: object, *args: object, **kwargs: object
    ) -> dict[str, object]:
        calls.append((*args, kwargs))
        return {
            "id": "clip-1",
            "name": "Chime",
            "appId": "com.example.agent",
        }

    monkeypatch.setattr(
        client_module._websocket.AudioClipWebSocket, "send_command", send_command
    )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SonosClient("192.168.1.10", http_client=http)
            await client.play_audio_clip(app_id="com.example.agent", name="Chime")
            assert client.uid == "RINCON_DIRECT"

    asyncio.run(run())

    command = calls[0][0]
    assert isinstance(command, dict)
    assert command["playerId"] == "RINCON_DIRECT"


def test_player_id_is_fetched_once_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    identity_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal identity_requests
        identity_requests += 1
        return httpx.Response(
            200,
            text=(
                '<root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
                "<UDN>uuid:RINCON_CACHED</UDN>"
                "</device></root>"
            ),
        )

    async def send_command(
        self: object, *args: object, **kwargs: object
    ) -> dict[str, object]:
        return {}

    monkeypatch.setattr(
        client_module._websocket.AudioClipWebSocket, "send_command", send_command
    )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SonosClient("192.168.1.10", http_client=http)
            await client.cancel_audio_clip("clip-1")
            await client.cancel_audio_clip("clip-2")

    asyncio.run(run())

    assert identity_requests == 1


def test_close_leaves_externally_provided_http_client_open() -> None:
    async def run() -> bool:
        http = httpx.AsyncClient()
        client = SonosClient("192.168.1.10", http_client=http)
        await client.close()
        return http.is_closed

    assert _run(run()) is False


@pytest.mark.parametrize(
    ("method", "action", "extra_args"),
    [
        ("play", "Play", {"Speed": "1"}),
        ("pause", "Pause", {}),
        ("stop", "Stop", {}),
        ("next", "Next", {}),
        ("previous", "Previous", {}),
    ],
)
def test_simple_transport_commands(
    recorder: _RecordingSoap, method: str, action: str, extra_args: dict[str, str]
) -> None:
    client = SonosClient("192.168.1.10")

    _run(getattr(client, method)())

    (endpoint, urn, called_action, args) = recorder.calls[0]
    assert endpoint == "http://192.168.1.10:1400/MediaRenderer/AVTransport/Control"
    assert urn == "urn:schemas-upnp-org:service:AVTransport:1"
    assert called_action == action
    assert args == {"InstanceID": "0", **extra_args}


def test_seek_queue_targets_track_number(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")

    _run(client.seek_queue(3))

    assert recorder.calls[0][2] == "Seek"
    assert recorder.calls[0][3] == {
        "InstanceID": "0",
        "Unit": "TRACK_NR",
        "Target": "3",
    }


def test_seek_targets_relative_time(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")

    _run(client.seek("0:01:30"))

    assert recorder.calls[0][3] == {
        "InstanceID": "0",
        "Unit": "REL_TIME",
        "Target": "0:01:30",
    }


def test_shuffle_and_repeat_preserve_each_other(recorder: _RecordingSoap) -> None:
    recorder._responses["GetTransportSettings"] = {"PlayMode": "REPEAT_ONE"}
    client = SonosClient("192.168.1.10")

    assert _run(client.set_shuffle(True)) == "SHUFFLE_REPEAT_ONE"

    recorder._responses["GetTransportSettings"] = {"PlayMode": "SHUFFLE"}
    assert _run(client.set_repeat("off")) == "SHUFFLE_NOREPEAT"
    set_calls = [call for call in recorder.calls if call[2] == "SetPlayMode"]
    assert [call[3]["NewPlayMode"] for call in set_calls] == [
        "SHUFFLE_REPEAT_ONE",
        "SHUFFLE_NOREPEAT",
    ]


def test_set_repeat_without_shuffle_uses_non_shuffled_play_modes(
    recorder: _RecordingSoap,
) -> None:
    recorder._responses["GetTransportSettings"] = {"PlayMode": "NORMAL"}
    client = SonosClient("192.168.1.10")

    assert _run(client.set_repeat("one")) == "REPEAT_ONE"


@pytest.mark.parametrize(
    ("current_play_mode", "expected_mode"),
    [
        ("REPEAT_ALL", "SHUFFLE"),
        ("SHUFFLE", "SHUFFLE"),
        ("NORMAL", "SHUFFLE_NOREPEAT"),
    ],
)
def test_set_shuffle_maps_every_current_repeat_state(
    recorder: _RecordingSoap, current_play_mode: str, expected_mode: str
) -> None:
    recorder._responses["GetTransportSettings"] = {"PlayMode": current_play_mode}
    client = SonosClient("192.168.1.10")

    assert _run(client.set_shuffle(True)) == expected_mode


def test_crossfade_get_and_set(recorder: _RecordingSoap) -> None:
    recorder._responses["GetCrossfadeMode"] = {"CrossfadeMode": "1"}
    client = SonosClient("192.168.1.10")

    assert _run(client.get_crossfade()) is True
    _run(client.set_crossfade(False))

    assert recorder.calls[-1][3]["CrossfadeMode"] == "0"


def test_configure_sleep_timer(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")

    _run(client.configure_sleep_timer("0:30:00"))
    _run(client.configure_sleep_timer(None))

    calls = [call for call in recorder.calls if call[2] == "ConfigureSleepTimer"]
    assert [call[3]["NewSleepTimerDuration"] for call in calls] == ["0:30:00", ""]


def test_play_uri_sets_transport_uri_then_plays(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")

    _run(client.play_uri("http://stream", title="Radio", radio=True))

    actions = [call[2] for call in recorder.calls]
    assert actions == ["SetAVTransportURI", "Play"]
    set_args = recorder.calls[0][3]
    assert set_args["CurrentURI"] == "x-rincon-mp3radio://stream"
    assert "Radio" in set_args["CurrentURIMetaData"]


def test_play_uri_without_radio_sends_empty_metadata(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")

    _run(client.play_uri("http://stream"))

    assert recorder.calls[0][3]["CurrentURIMetaData"] == ""


def test_open_plays_favorite_directly(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")
    favorite = Favorite(title="Jazz", uri="x-rincon-cpcontainer:1", metadata="<meta/>")

    position = _run(client.open(favorite))

    assert position is None
    actions = [call[2] for call in recorder.calls]
    assert actions == ["SetAVTransportURI", "Play"]
    assert recorder.calls[0][3]["CurrentURI"] == "x-rincon-cpcontainer:1"


def test_open_falls_back_to_play_uri_for_plain_string(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")

    position = _run(client.open("http://stream", title="Radio", radio=True))

    assert position is None
    assert recorder.calls[0][2] == "SetAVTransportURI"


def test_enqueue_uri_returns_parsed_position(recorder: _RecordingSoap) -> None:
    recorder._responses["AddURIToQueue"] = {"FirstTrackNumberEnqueued": "5"}
    client = SonosClient("192.168.1.10")

    position = _run(client.enqueue_uri("http://stream", metadata="<meta/>"))

    assert position == 5
    assert recorder.calls[0][3]["EnqueuedURI"] == "http://stream"
    assert recorder.calls[0][3]["EnqueueAsNext"] == "0"


def test_enqueue_uri_next_flag_maps_to_enqueue_as_next(
    recorder: _RecordingSoap,
) -> None:
    client = SonosClient("192.168.1.10")

    _run(client.enqueue_uri("http://stream", next_=True))

    assert recorder.calls[0][3]["EnqueueAsNext"] == "1"


def test_enqueue_uri_returns_none_when_position_missing(
    recorder: _RecordingSoap,
) -> None:
    client = SonosClient("192.168.1.10")

    position = _run(client.enqueue_uri("http://stream"))

    assert position is None


def test_enqueue_uri_with_play_seeks_and_plays(recorder: _RecordingSoap) -> None:
    recorder._responses["AddURIToQueue"] = {"FirstTrackNumberEnqueued": "5"}
    client = SonosClient("192.168.1.10")

    position = _run(client.enqueue_uri("http://stream", play=True))

    assert position == 5
    actions = [call[2] for call in recorder.calls]
    assert actions == ["AddURIToQueue", "Seek", "Play"]


def test_line_in_uses_explicit_speaker_source(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")
    source = Speaker(ip="192.168.1.11", room_name="Office", uid="RINCON_SRC")

    _run(client.line_in(source))

    assert recorder.calls[0][3]["CurrentURI"] == "x-rincon-stream:RINCON_SRC"


def test_line_in_uses_own_uid_when_no_source_given(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10", uid="RINCON_SELF")

    _run(client.line_in())

    assert recorder.calls[0][3]["CurrentURI"] == "x-rincon-stream:RINCON_SELF"


def test_line_in_raises_without_source_or_uid(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")

    with pytest.raises(ValueError, match="line-in playback requires"):
        _run(client.line_in())


def test_tv_requires_speaker_uid() -> None:
    client = SonosClient("192.168.1.10")

    with pytest.raises(ValueError, match="tv playback requires"):
        _run(client.tv())


def test_tv_plays_optical_input(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10", uid="RINCON_SELF")

    _run(client.tv())

    assert recorder.calls[0][3]["CurrentURI"] == "x-sonos-htastream:RINCON_SELF:spdif"


def test_get_volume_reads_master_channel(recorder: _RecordingSoap) -> None:
    recorder._responses["GetVolume"] = {"CurrentVolume": "42"}
    client = SonosClient("192.168.1.10")

    volume = _run(client.get_volume())

    assert volume == 42
    assert recorder.calls[0][3]["Channel"] == "Master"


def test_set_volume_clamps_to_valid_range(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")

    _run(client.set_volume(150))

    assert recorder.calls[0][3]["DesiredVolume"] == "100"


def test_adjust_volume_clamps_and_returns_new_level(
    recorder: _RecordingSoap,
) -> None:
    recorder._responses["GetVolume"] = {"CurrentVolume": "95"}
    client = SonosClient("192.168.1.10")

    new_volume = _run(client.adjust_volume(10))

    assert new_volume == 100
    set_call = next(call for call in recorder.calls if call[2] == "SetVolume")
    assert set_call[3]["DesiredVolume"] == "100"


def test_group_volume_get_set_and_adjust(recorder: _RecordingSoap) -> None:
    recorder._responses["GetGroupVolume"] = {"CurrentVolume": "20"}
    client = SonosClient("192.168.1.10")

    assert _run(client.get_group_volume()) == 20

    _run(client.set_group_volume(-5))
    set_call = next(call for call in recorder.calls if call[2] == "SetGroupVolume")
    assert set_call[3]["DesiredVolume"] == "0"

    new_volume = _run(client.adjust_group_volume(5))
    assert new_volume == 25


def test_mute_get_set_and_toggle(recorder: _RecordingSoap) -> None:
    recorder._responses["GetMute"] = {"CurrentMute": "1"}
    client = SonosClient("192.168.1.10")

    assert _run(client.get_mute()) is True

    _run(client.set_mute(False))
    set_call = next(call for call in recorder.calls if call[2] == "SetMute")
    assert set_call[3]["DesiredMute"] == "0"

    toggled = _run(client.toggle_mute())
    assert toggled is False


def test_get_transport_info_parses_response(recorder: _RecordingSoap) -> None:
    recorder._responses["GetTransportInfo"] = {
        "CurrentTransportState": "PLAYING",
        "CurrentTransportStatus": "OK",
        "CurrentSpeed": "1",
    }
    client = SonosClient("192.168.1.10")

    info = _run(client.get_transport_info())

    assert isinstance(info, TransportInfo)
    assert info.state is not None
    assert info.state.value == "PLAYING"


def test_get_transport_info_treats_unknown_state_as_none(
    recorder: _RecordingSoap,
) -> None:
    recorder._responses["GetTransportInfo"] = {"CurrentTransportState": "BOGUS"}
    client = SonosClient("192.168.1.10")

    info = _run(client.get_transport_info())

    assert info.state is None


def test_get_position_info_coerces_track_number(recorder: _RecordingSoap) -> None:
    recorder._responses["GetPositionInfo"] = {"Track": "3", "TrackURI": "x-sonos:1"}
    client = SonosClient("192.168.1.10")

    info = _run(client.get_position_info())

    assert isinstance(info, PositionInfo)
    assert info.track == 3
    assert info.track_uri == "x-sonos:1"


def test_now_playing_assembles_playback_state(recorder: _RecordingSoap) -> None:
    recorder._responses["GetTransportInfo"] = {"CurrentTransportState": "PLAYING"}
    recorder._responses["GetPositionInfo"] = {
        "Track": "1",
        "TrackURI": "x-sonos:1",
        "RelTime": "0:01:00",
        "TrackDuration": "0:03:30",
    }
    client = SonosClient("192.168.1.10")

    playback = _run(client.now_playing())

    assert playback.state == "PLAYING"
    assert playback.relative_time == "0:01:00"
    assert playback.track_duration == "0:03:30"
    assert playback.track is not None
    assert playback.track.uri == "x-sonos:1"


def test_queue_lists_tracks_with_sequential_positions(
    recorder: _RecordingSoap,
) -> None:
    didl = (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        "<item><dc:title>Song A</dc:title><res>x-1</res></item>"
        "<item><dc:title>Song B</dc:title><res>x-2</res></item>"
        "</DIDL-Lite>"
    )
    recorder._responses["Browse"] = {"Result": didl}
    client = SonosClient("192.168.1.10")

    tracks = _run(client.queue(start=10))

    assert [track.position for track in tracks] == [11, 12]
    assert [track.title for track in tracks] == ["Song A", "Song B"]
    assert recorder.calls[0][1] == "urn:schemas-upnp-org:service:ContentDirectory:1"


def test_clear_queue_and_remove_queue_item(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")

    _run(client.clear_queue())
    assert recorder.calls[0][2] == "RemoveAllTracksFromQueue"

    _run(client.remove_queue_item(4))
    assert recorder.calls[1][3]["ObjectID"] == "Q:0/4"


def test_favorites_parses_browse_response(recorder: _RecordingSoap) -> None:
    didl = (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        "<item><dc:title>Jazz FM</dc:title><res>x-rincon:1</res></item>"
        "</DIDL-Lite>"
    )
    recorder._responses["Browse"] = {"Result": didl}
    client = SonosClient("192.168.1.10")

    favorites = _run(client.favorites())

    assert [favorite.title for favorite in favorites] == ["Jazz FM"]
    assert recorder.calls[0][3]["ObjectID"] == "FV:2"


def test_open_favorite_sets_uri_and_plays(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")
    favorite = Favorite(title="Jazz", uri="x-rincon-cpcontainer:1", metadata="<meta/>")

    _run(client.open_favorite(favorite))

    actions = [call[2] for call in recorder.calls]
    assert actions == ["SetAVTransportURI", "Play"]
    assert recorder.calls[0][3]["CurrentURIMetaData"] == "<meta/>"


def test_join_and_unjoin(recorder: _RecordingSoap) -> None:
    client = SonosClient("192.168.1.10")

    _run(client.join("RINCON_OTHER"))
    assert recorder.calls[0][3]["CurrentURI"] == "x-rincon:RINCON_OTHER"

    _run(client.unjoin())
    assert recorder.calls[1][2] == "BecomeCoordinatorOfStandaloneGroup"


def test_join_strips_uuid_prefix_from_string_source(
    recorder: _RecordingSoap,
) -> None:
    client = SonosClient("192.168.1.10")

    _run(client.join("uuid:RINCON_OTHER"))

    assert recorder.calls[0][3]["CurrentURI"] == "x-rincon:RINCON_OTHER"


def test_watch_returns_configured_event_subscription() -> None:
    client = SonosClient("192.168.1.10", port=1401)

    subscription = client.watch(timeout_seconds=60)

    assert isinstance(subscription, EventSubscription)
    assert subscription.ip == "192.168.1.10"
    assert subscription.port == 1401
    assert subscription.timeout_seconds == 60


def test_get_zone_group_state_and_room_name(recorder: _RecordingSoap) -> None:
    recorder._responses["GetZoneGroupState"] = {"ZoneGroupState": "<state/>"}
    recorder._responses["GetZoneAttributes"] = {"CurrentZoneName": "Kitchen"}
    client = SonosClient("192.168.1.10")

    assert _run(client.get_zone_group_state()) == "<state/>"
    assert _run(client.get_room_name()) == "Kitchen"
