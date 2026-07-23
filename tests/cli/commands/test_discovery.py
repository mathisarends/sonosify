import asyncio
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner

from sonosify import AVTransportEvent, RenderingControlEvent, TransportState
from sonosify.cli.app import app
from sonosify.cli.commands import discovery
from sonosify.models import PlaybackState, Track


class _NowPlayingClient:
    def __init__(self, playback: PlaybackState) -> None:
        self._playback = playback

    async def now_playing(self) -> PlaybackState:
        return self._playback


def test_now_playing_shows_track_details_when_something_is_playing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playback = PlaybackState(
        state="PLAYING",
        track=Track(title="Song", creator="Artist"),
        relative_time="0:01:00",
    )

    @asynccontextmanager
    async def fake_client_for(room, ip, *, coordinator=True):
        yield _NowPlayingClient(playback)

    monkeypatch.setattr(discovery, "client_for", fake_client_for)

    result = CliRunner().invoke(app, ["now-playing"])

    assert result.exit_code == 0
    assert "Song" in result.output
    assert "Artist" in result.output


def test_now_playing_reports_nothing_playing_when_no_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playback = PlaybackState(state="STOPPED", track=None)

    @asynccontextmanager
    async def fake_client_for(room, ip, *, coordinator=True):
        yield _NowPlayingClient(playback)

    monkeypatch.setattr(discovery, "client_for", fake_client_for)

    result = CliRunner().invoke(app, ["now-playing"])

    assert result.exit_code == 0
    assert "nothing playing" in result.output


class _Watcher:
    def __init__(self, events: list[object]) -> None:
        self.ip = "192.168.1.10"
        self._events = list(events)

    async def __aenter__(self) -> "_Watcher":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_Watcher":
        return self

    async def __anext__(self) -> object:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


class _FakeController:
    def __init__(self, events: list[object], *, timeout: float = 15.0) -> None:
        self._events = events

    def watch(self, room, *, ip=None):  # type: ignore[no-untyped-def]
        return _Watcher(self._events)


def test_watch_dispatches_known_events_by_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        AVTransportEvent(values={}, transport_state=TransportState.PLAYING),
        RenderingControlEvent(values={}, volume=20, muted=False),
    ]
    monkeypatch.setattr(
        discovery, "SonosController", lambda **kwargs: _FakeController(events)
    )

    result = CliRunner().invoke(app, ["watch"])

    assert result.exit_code == 0
    assert "transport" in result.output
    assert "rendering volume=20" in result.output


def test_watch_stops_quietly_on_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    class _CancellingWatcher(_Watcher):
        def __aiter__(self) -> "_CancellingWatcher":
            return self

        async def __anext__(self) -> object:
            raise asyncio.CancelledError

    class _CancellingController(_FakeController):
        def watch(self, room, *, ip=None):  # type: ignore[no-untyped-def]
            return _CancellingWatcher([])

    monkeypatch.setattr(
        discovery, "SonosController", lambda **kwargs: _CancellingController([])
    )

    result = CliRunner().invoke(app, ["watch"])

    assert result.exit_code == 0
    assert "stopped watching" in result.output
