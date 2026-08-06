# 🔊 sonosify

![CI](https://github.com/mathisarends/sonosify/actions/workflows/ci.yaml/badge.svg)
![Python](https://img.shields.io/badge/python-3.13%20%7C%203.14-blue)
![PyPI](https://img.shields.io/pypi/v/sonosify)
![License](https://img.shields.io/badge/license-MIT-informational)

Programmatic Python API for discovering and controlling Sonos speakers on a local
network.

![sonosify banner](static/sonosify_banner.png)

An async Python API for discovery, playback, volume, queue, groups, favorites,
audio clips, and live UPnP event subscriptions. Everything runs against the
speakers on your LAN — no cloud account, no API keys.

## Table of contents

- [Installation](#installation)
- [Quickstart](#quickstart)
- [Architecture](#architecture)
- [API reference](#api-reference)
  - [`SonosController`](#sonoscontroller)
  - [`SonosSystem`](#sonossystem)
  - [`SonosClient`](#sonosclient)
    - [Transport control](#transport-control)
    - [Volume and mute](#volume-and-mute)
    - [Status](#status)
    - [Queue](#queue)
    - [Playback modes](#playback-modes)
    - [Favorites](#favorites)
    - [Grouping](#grouping)
    - [Line-in and TV](#line-in-and-tv)
    - [Audio clips](#audio-clips)
  - [Live events](#live-events)
  - [Data models](#data-models)
  - [Errors](#errors)
- [Examples](#examples)
- [Contributing](#contributing)
- [License](#license)

## Installation

Requires **Python 3.13 or 3.14**. Sonos speakers must be reachable on the same
local network (SSDP discovery uses UDP multicast).

```powershell
uv add sonosify
# or: pip install sonosify
```

From a local checkout of this repository:

```powershell
uv pip install -e .
```

Setting up a development environment (dependency groups, tests, linting,
pre-commit) is covered in [CONTRIBUTING.md](CONTRIBUTING.md).

## Quickstart

```python
import asyncio

from sonosify import SonosController


async def main():
    sonos = SonosController()
    system = await sonos.discover()

    print([speaker.room_name for speaker in system.speakers])

    async with await sonos.client("Kitchen") as kitchen:
        await kitchen.pause()
        await kitchen.set_volume(25)
        print(await kitchen.now_playing())


asyncio.run(main())
```

Lower-level direct device access is also available, bypassing discovery entirely:

```python
import asyncio

from sonosify import SonosClient


async def main():
    async with SonosClient("192.168.1.42") as speaker:
        await speaker.play_uri("https://example.com/live.mp3", radio=True, title="Example Radio")


asyncio.run(main())
```

## Architecture

The public surface is fully async and built from three layers:

| Layer | Type | Responsibility |
| --- | --- | --- |
| Household | `SonosController` | Discovery, caching the topology, convenience shortcuts, watching |
| Topology | `SonosSystem` | Snapshot of speakers and groups; resolves a room name to a speaker |
| Device | `SonosClient` | Every command against one speaker (UPnP/SOAP + local WebSocket) |

`SonosController` is the normal entry point: it runs SSDP discovery once, keeps
the resulting `SonosSystem`, and hands out `SonosClient` instances. Use
`SonosClient` directly when you already know a speaker's IP address and want to
skip discovery.

Both `SonosClient` and `EventSubscription` are async context managers and should
be closed — `async with` handles that for you.

## API reference

### `SonosController`

Household-wide entry point. Import from `sonosify`.

```python
SonosController(
    *,
    timeout: float = 15.0,            # per-request HTTP timeout
    discovery_timeout: float = 2.0,   # SSDP listen window
    include_invisible: bool = False,  # include satellites/bonded players
)
```

| Method | Returns | Description |
| --- | --- | --- |
| `await discover()` | `SonosSystem` | Runs SSDP discovery, reads the zone group topology, caches the result on the controller |
| `await client(room=None, *, ip=None, coordinator=True)` | `SonosClient` | Resolves a room name to a speaker and returns a client. Discovers on first use unless `ip` is given, which bypasses discovery entirely. `coordinator=True` redirects to the group coordinator, which is what transport commands must target |
| `watch(room=None, *, ip=None, coordinator=True, services=..., callback_host=None, callback_port=0, timeout_seconds=300)` | async context manager → `EventSubscription` | Subscribes to live UPnP events for one speaker (see [Live events](#live-events)) |
| `await play(room=None, *, ip=None)` | `None` | One-shot shortcut: open a client, send the command, close it |
| `await pause(room=None, *, ip=None)` | `None` | As above |
| `await stop(room=None, *, ip=None)` | `None` | As above |
| `await set_volume(volume, room=None, *, ip=None)` | `None` | As above, but targets the individual speaker (`coordinator=False`) |

Read-only properties: `timeout`, `discovery_timeout`, `include_invisible`, and
`system` (the cached `SonosSystem`, or `None` before the first discovery).

The module-level `discover()` function is exported too, if you want a
`SonosSystem` without holding on to a controller:

```python
from sonosify import discover

system = await discover(timeout=15.0, discovery_timeout=2.0, include_invisible=False)
```

### `SonosSystem`

An immutable snapshot of the household returned by `discover()`. Re-run
discovery to pick up grouping changes.

| Member | Returns | Description |
| --- | --- | --- |
| `speakers` | `tuple[Speaker, ...]` | All discovered speakers |
| `groups` | `tuple[Group, ...]` | Zone groups with their members |
| `find(query=None, *, ip=None, include_invisible=False)` | `Speaker` | Resolves a room name: exact case-insensitive match first, then substring match. Raises `AmbiguousSpeakerError` on multiple substring hits, `SpeakerNotFoundError` on none. With no `query` it returns the only speaker, if there is exactly one |
| `coordinator_for(speaker)` | `Speaker` | The group coordinator for a speaker, or the speaker itself when standalone |
| `client(query=None, *, ip=None, coordinator=True, include_invisible=False)` | `SonosClient` | `find()` plus `SonosClient.from_speaker()` |

### `SonosClient`

All commands for a single speaker. Speaks UPnP/SOAP over HTTP on port 1400,
plus the local Control API WebSocket for audio clips.

```python
SonosClient(
    ip: str,
    *,
    port: int = 1400,
    uid: str = "",                              # RINCON uid; auto-fetched when needed
    timeout: float = 15.0,
    http_client: httpx.AsyncClient | None = None,  # inject to share a connection pool
)

SonosClient.from_speaker(speaker, *, timeout=15.0)  # classmethod
```

Properties: `ip`, `port`, `uid`, `base_url`. Use it as an async context manager,
or call `await close()` yourself. A client constructed with an injected
`http_client` does not close that client.

#### Transport control

| Method | Description |
| --- | --- |
| `await play()` / `await pause()` / `await stop()` | Basic transport |
| `await next()` / `await previous()` | Skip within the queue |
| `await seek(position)` | Seek inside the current track; `position` is an `"H:MM:SS"` string |
| `await seek_queue(position)` | Jump to a 1-based queue position |
| `await play_uri(uri, *, title="", radio=False)` | Set the transport URI and start playing. `radio=True` rewrites the URI to `x-rincon-mp3radio://` and generates stream metadata |
| `await open(value, *, title="", radio=False)` | Accepts a URI string or a `Favorite` and dispatches to `play_uri()` / `open_favorite()` |

#### Volume and mute

Speaker-level and group-level volume are separate controls. Group volume scales
every member of the group at once.

| Method | Returns | Description |
| --- | --- | --- |
| `await get_volume()` | `int` | 0–100 |
| `await set_volume(volume)` | `None` | Clamped to 0–100 |
| `await adjust_volume(delta)` | `int` | Relative change; returns the new volume |
| `await get_group_volume()` / `await set_group_volume(volume)` / `await adjust_group_volume(delta)` | | Same three operations for the whole group |
| `await get_mute()` | `bool` | |
| `await set_mute(muted)` | `None` | |
| `await toggle_mute()` | `bool` | Returns the new mute state |

#### Status

| Method | Returns | Description |
| --- | --- | --- |
| `await now_playing()` | `PlaybackState` | Combines transport state, the parsed current `Track`, elapsed time, and duration |
| `await get_transport_info()` | `TransportInfo` | Raw `GetTransportInfo` result: `state` (`TransportState`), `status`, `speed` |
| `await get_position_info()` | `PositionInfo` | Raw `GetPositionInfo` result: track number, URI, duration, metadata, relative/absolute time |
| `await get_room_name()` | `str` | The speaker's zone name |
| `await get_zone_group_state()` | `str` | Raw zone group topology XML (used internally by discovery) |

#### Queue

| Method | Returns | Description |
| --- | --- | --- |
| `await queue(*, start=0, count=100)` | `list[Track]` | Paginated queue listing with 1-based `position` on each track |
| `await enqueue_uri(uri, *, metadata="", next_=False, play=False)` | `int \| None` | Adds a URI to the queue; returns the assigned position. `next_=True` inserts after the current track, `play=True` jumps to it and starts playback |
| `await remove_queue_item(position)` | `None` | Removes one item by queue position |
| `await clear_queue()` | `None` | Empties the queue |

#### Playback modes

Sonos encodes shuffle and repeat in a single `PlayMode` string. The helpers
below read the current mode, flip one dimension, and write it back, so setting
shuffle preserves repeat and vice versa.

| Method | Returns | Description |
| --- | --- | --- |
| `await get_play_mode()` | `str` | Raw mode, e.g. `NORMAL`, `SHUFFLE`, `REPEAT_ONE` |
| `await set_play_mode(mode)` | `None` | Sets the raw mode |
| `await set_shuffle(enabled)` | `str` | Toggles shuffle, keeps repeat; returns the resulting mode |
| `await set_repeat(repeat)` | `str` | Takes `"off"` / `"one"` / `"all"`, keeps shuffle; returns the resulting mode |
| `await get_crossfade()` / `await set_crossfade(enabled)` | `bool` / `None` | Crossfade between tracks |
| `await configure_sleep_timer(duration)` | `None` | `"H:MM:SS"` string, or `None` to cancel |

#### Favorites

| Method | Returns | Description |
| --- | --- | --- |
| `await favorites()` | `list[Favorite]` | Sonos Favorites (`FV:2`), with the DIDL metadata needed to play them |
| `await open_favorite(favorite)` | `None` | Sets the favorite as the transport URI and plays |

#### Grouping

| Method | Description |
| --- | --- |
| `await join(coordinator)` | Joins the group of a `Speaker` or RINCON uid — this speaker becomes a follower |
| `await unjoin()` | Leaves the group and becomes a standalone coordinator |

#### Line-in and TV

| Method | Description |
| --- | --- |
| `await line_in(source=None)` | Plays the analog line-in of `source` (a `Speaker`, a RINCON uid, or this speaker when omitted) |
| `await tv()` | Switches a soundbar to its TV/S-PDIF input; requires a client that knows its `uid` |

#### Audio clips

Audio clips play a short sound *over* whatever is currently playing and then
restore it — ideal for TTS and notification sounds. They use the player's local
Control API WebSocket, which targets the speaker's immutable player ID, so
discovery (or a `uid`) is required.

```python
import asyncio

from sonosify import ClipPriority, ClipType, SonosController


async def main():
    sonos = SonosController()
    async with await sonos.client("Kitchen") as kitchen:
        clip = await kitchen.play_audio_clip(
            "http://192.168.1.50:8000/tts/response.mp3",
            app_id="com.example.voice-agent",
            name="Agent Voice",
            volume=30,
            priority=ClipPriority.HIGH,
            clip_type=ClipType.VOICE_ASSISTANT,
        )
        print(clip.id)


asyncio.run(main())
```

| Method | Returns | Description |
| --- | --- | --- |
| `await play_audio_clip(stream_url=None, *, app_id, name="sonosify", volume=None, priority=ClipPriority.LOW, clip_type=None, http_authorization=None, led_behavior=ClipLEDBehavior.NONE)` | `AudioClip` | Schedules a clip. Omitting `stream_url` plays the built-in chime |
| `await play_audio_clip_data(audio, *, content_type="audio/wav", local_host=None, app_id, name="sonosify", volume=None, priority=ClipPriority.LOW, clip_type=None, led_behavior=ClipLEDBehavior.NONE)` | `HostedAudioClip` | Hosts complete WAV or MP3 data temporarily and schedules it as a clip |
| `await cancel_audio_clip(clip_id)` | `None` | Cancels a scheduled or active clip |

Arguments are validated before the request: `name` 1–64 characters, `app_id`
1–127 characters, `volume` 0–100, `stream_url` an absolute HTTP(S) URL,
`http_authorization` at most 512 bytes.

Enums: `ClipPriority` (`LOW`, `HIGH`), `ClipType` (`CHIME`, `CUSTOM`,
`VOICE_ASSISTANT`), `ClipLEDBehavior` (`NONE`, `WHITE_LED_QUICK_BREATHING`).

The player must expose the `AUDIO_CLIP` capability, and it must be able to fetch
the supplied HTTP(S) URL itself. A client keeps its local command WebSocket open
so a subsequent `cancel_audio_clip` does not require another connection
handshake. If the player closes the socket, the next command reconnects.

For audio already available in memory, `play_audio_clip_data` lazily starts a
small HTTP server on the local machine and chooses the LAN address that routes
to the player. The returned handle distinguishes a successful HTTP fetch from
the terminal playback status reported by Sonos:

```python
handle = await kitchen.play_audio_clip_data(
    response.audio,
    content_type="audio/wav",
    app_id="com.example.voice-agent",
    name="Agent Voice",
    priority=ClipPriority.HIGH,
    clip_type=ClipType.VOICE_ASSISTANT,
)

await handle.wait_until_fetched(timeout=10)
clip = await handle.wait_until_finished(timeout=60)
print(clip.status)  # DONE, INTERRUPTED, DISMISSED, or ERROR
```

`local_host` can override the advertised address on machines with unusual
network routing. The temporary server and all remaining clip data are released
when the client closes. `HostedAudioClip.close()` can release one clip earlier.

### Live events

Live updates use Sonos UPnP event subscriptions. `EventSubscription` starts a
local HTTP callback server, subscribes the speaker to it, and yields parsed
events — your OS firewall may ask whether Python can accept incoming
connections.

Register handlers with `on()` and let `run()` do the dispatching. Handlers are
selected by event class, may be sync or async, and run in registration order:

```python
import asyncio

from sonosify import AVTransportEvent, RenderingControlEvent, SonosController


async def main():
    sonos = SonosController()
    async with sonos.watch("Kitchen") as watcher:

        @watcher.on(AVTransportEvent)
        def transport(event):
            print(event.transport_state, event.track.title if event.track else "")

        @watcher.on(RenderingControlEvent)
        async def rendering(event):
            print(event.volume, event.muted)

        await watcher.run()


asyncio.run(main())
```

`@watcher.on(A, B)` registers one handler for several event classes, and
`@watcher.on()` receives everything. The iterator form still works if you prefer
`match` over handlers:

```python
async for event in watcher:
    match event:
        case AVTransportEvent(transport_state=state):
            print(state)
```

`SonosController.watch()` is the convenient form; `SonosClient.watch()` returns
the same `EventSubscription` for a client you already hold.

| Member | Description |
| --- | --- |
| `async with subscription` | Starts the callback server and subscribes; unsubscribes and shuts down on exit |
| `@subscription.on(*event_types)` | Registers a handler; no arguments means every event |
| `await run()` | Starts if needed, then dispatches every incoming event to the handlers, indefinitely |
| `async for event in subscription` | Yields events as they arrive, indefinitely |
| `await next_event(timeout=None)` | Single event, optionally bounded by a timeout (raises `TimeoutError`) |
| `events(*, timeout=None)` | Async iterator form of `next_event()` |
| `await start()` / `await close()` | Manual lifecycle, if you are not using `async with` |
| `services` / `subscribed_services` | The services you asked for, and the ones the player actually accepted |

Subscriptions are renewed automatically at half their `timeout_seconds`, so a
watcher keeps running past the player's subscription lifetime.

No player implements every service — a speaker answers `SUBSCRIBE` on the
soundbar-only `HTControl` with `503`. Those services are skipped and listed in
`subscribed_services`; only if the player accepts nothing at all does `start()`
raise `SubscriptionError`. That makes `services=ALL_SERVICES` safe on any model.

#### Event types

Every service Sonos documents with evented state variables has its own frozen
model. All of them carry `service`, the raw `values` dict, `sequence`, and `sid`;
the typed fields below are the documented state variables of that service, and
anything not modelled stays available in `values`. Every field is optional
because a NOTIFY only carries the variables that actually changed.

| `EventService` | Type | Typed fields include |
| --- | --- | --- |
| `AV_TRANSPORT` | `AVTransportEvent` | `transport_state`, `play_mode`, `crossfade`, `track`, `next_track`, `enqueued_track`, `number_of_tracks`, `transport_actions`, `alarm_running` |
| `RENDERING_CONTROL` | `RenderingControlEvent` | `volume`, `muted`, `bass`, `treble`, `loudness`, `night_mode`, `dialog_level`, `sub_enabled`, `surround_enabled`, `trueplay_enabled` |
| `GROUP_RENDERING_CONTROL` | `GroupRenderingControlEvent` | `group_volume`, `group_muted`, `group_volume_changeable` |
| `QUEUE` | `QueueEvent` | `update_id`, `queue_owner_id`, `curated` |
| `CONTENT_DIRECTORY` | `ContentDirectoryEvent` | `system_update_id`, `container_update_ids`, `favorites_update_id`, `share_index_in_progress` |
| `ZONE_GROUP_TOPOLOGY` | `ZoneGroupTopologyEvent` | `zone_group_state`, `zone_group_id`, `zone_player_uuids_in_group`, `available_software_update` |
| `DEVICE_PROPERTIES` | `DevicePropertiesEvent` | `zone_name`, `icon`, `invisible`, `orientation`, `mic_enabled`, `wifi_enabled`, `supports_audio_clip` |
| `ALARM_CLOCK` | `AlarmClockEvent` | `alarm_list_version`, `time_zone`, `time_server`, `time_format` |
| `AUDIO_IN` | `AudioInEvent` | `audio_input_name`, `line_in_connected`, `playing`, `left_line_in_level` |
| `HT_CONTROL` | `HTControlEvent` | `ir_repeater_state`, `remote_configured`, `tos_link_connected` |
| `GROUP_MANAGEMENT` | `GroupManagementEvent` | `group_coordinator_is_local`, `local_group_uuid`, `reset_volume_after` |
| `MUSIC_SERVICES` | `MusicServicesEvent` | `service_list_version` |
| `SYSTEM_PROPERTIES` | `SystemPropertiesEvent` | `customer_id`, `update_id`, `voice_update_id` |
| `VIRTUAL_LINE_IN` | `VirtualLineInEvent` | `transport_state`, `current_track_uri` |
| `RENDERER_CONNECTION_MANAGER` | `RendererConnectionManagerEvent` | `source_protocol_info`, `sink_protocol_info`, `current_connection_ids` |
| `SERVER_CONNECTION_MANAGER` | `ServerConnectionManagerEvent` | same three, for the MediaServer side |
| — | `UnknownSonosEvent` | Fallback for a service this library does not model |

`SonosEvent` is the base class of all of them, so `@watcher.on(SonosEvent)`
matches everything and `event.values` is always available. `DEFAULT_SERVICES`
subscribes to `AV_TRANSPORT` and `RENDERING_CONTROL`; pass `ALL_SERVICES` to
`watch(services=...)` for the full set. `TransportState` enumerates `PLAYING`,
`PAUSED_PLAYBACK`, `STOPPED`, `TRANSITIONING`, and the remaining UPnP states;
`PlayMode` enumerates `NORMAL`, `SHUFFLE`, `REPEAT_ALL`, and the rest.

Values are coerced leniently: unknown enum members, non-numeric numbers, and
malformed flags become `None` rather than raising. For stereo pairs, the typed
field holds the `Master` channel and the other channels stay in `values` under
`Volume:LF`-style keys.

### Data models

All models are frozen Pydantic models.

| Model | Fields |
| --- | --- |
| `Speaker` | `ip`, `room_name`, `uid`, `zone_name`, `coordinator_uid`, `is_coordinator`, `invisible`, `port` |
| `Group` | `id`, `coordinator_uid`, `members`, plus a `coordinator` property |
| `Track` | `title`, `creator`, `album`, `uri`, `album_art_uri`, `duration`, `position` |
| `PlaybackState` | `state`, `track`, `relative_time`, `absolute_time`, `track_duration` |
| `Favorite` | `title`, `uri`, `metadata`, `album_art_uri` |
| `AudioClip` | `id`, `name`, `app_id`, `priority`, `clip_type`, `status`, `error_code` |
| `TransportInfo` | `state` (`TransportState`), `status`, `speed` |
| `PositionInfo` | `track`, `track_uri`, `track_duration`, `track_metadata`, `relative_time`, `absolute_time` |

### Errors

Every error derives from `SonosifyError` and exposes `error_details()`, a
dictionary with a stable machine-readable `code`.

| Error | Raised when | Extra |
| --- | --- | --- |
| `DiscoveryError` | SSDP found nothing, or no device metadata could be parsed | |
| `SpeakerNotFoundError` | No speaker matches the room name or IP | `query` |
| `AmbiguousSpeakerError` | A room name matches several speakers | `query`, `matches` |
| `NetworkError` | A speaker was unreachable or the HTTP request failed | |
| `UPnPError` | The speaker rejected a SOAP action | `code`, `description` |
| `SubscriptionError` | The speaker accepted none of the requested event subscriptions | `services` |
| `LocalAPIError` | The local WebSocket API returned an error (importable from `sonosify.errors`) | `response` |
| `UnsupportedFeatureError` | The player does not support the requested feature | |

## Examples

Runnable scripts for every area of the API are in [`examples/`](examples/):

```powershell
uv run python examples/discover.py
uv run python examples/now_playing.py Kitchen
uv run python examples/watch.py Kitchen
uv run python examples/play_radio.py Kitchen https://example.com/live.mp3 "Example Radio"
uv run python examples/local_audio_clip.py --volume 30  # uses SONOS_IP_ADDRESS
uv run python examples/resume_playback.py Kitchen
uv run python examples/volume.py Kitchen 25
uv run python examples/favorites.py Kitchen
uv run python examples/favorites.py Kitchen "Jazz FM"
uv run python examples/track_queue.py Kitchen
uv run python examples/track_queue.py Kitchen add "x-rincon-mp3radio://example.com/live.mp3"
uv run python examples/groups.py
uv run python examples/group.py join Kitchen "Living Room"
uv run python examples/group.py leave Kitchen
uv run python examples/playback_modes.py Kitchen shuffle on
uv run python examples/playback_modes.py Kitchen sleep 0:30:00
```

## Contributing

Bug reports and pull requests are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the development setup, test/lint
commands, and what CI checks on every push.

## License

MIT — see [LICENSE](LICENSE).
