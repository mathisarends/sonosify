# Emulating the full `sonoscli` surface

Goal: assess whether the `sonosify` library can already back every command in the
`sonoscli` command reference, and capture the gaps that need new library work
before the CLI (`sonosify/cli.py`) can reach feature parity.

Legend: ✅ fully backed by the lib · 🟡 partially backed / composable · ❌ no library support yet.

## Global flags

| Flag                              | Status | Notes                                                                                                                                                        |
| --------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--name`                          | ✅     | `SonosSystem.find(query)` / `SonosController.client(room)` (exact + substring match).                                                                        |
| `--ip`                            | ✅     | `ip=` on `find` / `client`; `SonosClient(ip)` direct.                                                                                                        |
| `--timeout`                       | ✅     | `timeout` / `discovery_timeout` params throughout.                                                                                                           |
| `--format` (plain/json/tsv)       | 🟡     | All models are `pydantic.BaseModel` → `.model_dump()`/JSON is trivial. CLI-level concern, no lib change needed, but a shared renderer in the CLI is missing. |
| `--debug` (SOAP traces to stderr) | ❌     | `soap.py` has no logging/trace hook. See **Gap: SOAP tracing**.                                                                                              |

## Command coverage

### Discovery & status

| Command          | Status | Library API                                                             |
| ---------------- | ------ | ----------------------------------------------------------------------- |
| `discover`       | ✅     | `discover()` / `SonosController.discover()` → `SonosSystem`.            |
| `status` / `now` | ✅     | `SonosClient.now_playing()` → `PlaybackState`.                          |
| `watch`          | ✅     | `SonosClient.watch()` → `EventSubscription` (AV transport + rendering). |

### Playback

| Command        | Status | Library API                                              |
| -------------- | ------ | -------------------------------------------------------- |
| `play`         | ✅     | `play()`                                                 |
| `pause`        | ✅     | `pause()`                                                |
| `stop`         | ✅     | `stop()`                                                 |
| `next`         | ✅     | `next()`                                                 |
| `prev`         | ✅     | `previous()`                                             |
| `play-url`     | ✅     | `play_uri(uri, radio=True, title=...)` (radio metadata). |
| `play-uri`     | ✅     | `play_uri(uri)` / `enqueue_uri(uri)`.                    |
| `play youtube` | ❌     | No YouTube resolution. See **Gap: YouTube**.             |
| `linein`       | ✅     | `line_in(source)`.                                       |
| `tv`           | ✅     | `tv()` (requires uid from discovery).                    |

### Volume & mute

| Command  | Status | Library API                                                                                                       |
| -------- | ------ | ----------------------------------------------------------------------------------------------------------------- |
| `volume` | 🟡     | `get_volume()` / `set_volume(n)`. Missing: **relative** (`+5`/`-5`), **group volume**, ramp. See **Gap: volume**. |
| `mute`   | ✅     | `get_mute()` / `set_mute()` / `toggle_mute()`.                                                                    |

### Grouping

| Command                            | Status | Library API                                                                                                              |
| ---------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------ |
| `group` (join/leave/party/ungroup) | ❌     | Topology is **read-only** today (`SonosSystem.groups`, `coordinator_for`). No join/leave actions. See **Gap: grouping**. |

### Queue

| Command                             | Status | Library API                                                                                          |
| ----------------------------------- | ------ | ---------------------------------------------------------------------------------------------------- |
| `queue` (list/clear/remove/play-at) | ✅     | `queue()`, `clear_queue()`, `remove_queue_item(pos)`, `seek_queue(pos)`, `enqueue_uri(uri, next_=)`. |

### Favorites & scenes

| Command                    | Status | Library API                                             |
| -------------------------- | ------ | ------------------------------------------------------- |
| `favorites`                | ✅     | `favorites()` → `list[Favorite]`, `open_favorite(fav)`. |
| `scene` (snapshot/restore) | ❌     | No state snapshot/restore. See **Gap: scenes**.         |

### Track playback

| Command   | Status | Library API                                                                      |
| --------- | ------ | -------------------------------------------------------------------------------- |
| `open`    | ✅     | `open(value)` handles `Favorite` objects and generic playable URIs.              |
| `enqueue` | ✅     | `enqueue_uri()`, CLI `enqueue`.                                                  |
| `track`   | ✅     | `open_track(..., play=True)` accepts a track id, track URI, or track share URL.  |

### Local config

| Command  | Status | Notes                                                                                                                                                                                      |
| -------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `config` | ✅     | `config set --room / --ip / --format / --timeout` persists defaults; `config show` / `config clear`. Loaded in `main` callback; `state.timeout` threaded into all `SonosController` calls. |

---

## Gaps requiring library work

Ordered roughly by value-to-effort.

### Gap: grouping (highest value)

`sonos group` needs join / leave / ungroup / party-mode. UPnP calls:

- **Join** a member to a coordinator: `SetAVTransportURI` with `CurrentURI=x-rincon:<coordinator_uid>`, empty metadata.
- **Leave / make standalone**: `BecomeCoordinatorOfStandaloneGroup` on AVTransport.
- **Party mode**: join every visible speaker to one coordinator.

Proposed API on `SonosClient`:

```python
async def join(self, coordinator: Speaker | str) -> None: ...
async def unjoin(self) -> None: ...   # BecomeCoordinatorOfStandaloneGroup
```

Plus `SonosController.party(coordinator_room)` / `ungroup_all()` helpers that iterate
`system.speakers`. Topology already gives us `coordinator_uid` for verification.

### Gap: scenes (snapshot / restore)

`sonos scene` snapshots a speaker's state and restores it later. Compose from existing
reads/writes — no new SOAP actions needed:

- Snapshot: `now_playing()` (transport state + track URI + position), `get_volume()`,
  `get_mute()`, and current `SetAVTransportURI` source. For queue-based sources also
  capture queue + track index.
- Restore: re-apply volume/mute, re-`SetAVTransportURI`, `seek_queue`, seek to
  `RelTime`, then `play`/`pause` to match prior state.

Proposed: a `Snapshot` pydantic model + `SonosClient.snapshot()` / `restore(snapshot)`.
This is mostly orchestration over methods that already exist.

### Gap: relative & group volume (small)

Extend volume handling:

- Relative: read `get_volume()`, clamp `current + delta`, `set_volume()`.
- Group volume: RenderingControl `SetGroupVolume` / `GetGroupVolume` (or apply to all
  members of the coordinator's group). Add `set_group_volume(n)` / `get_group_volume()`.

### Gap: SOAP tracing (`--debug`)

`soap.py::soap_call` should emit request/response traces. Add a module logger
(`logging.getLogger("sonosify.soap")`) logging endpoint, SOAPACTION, and bodies at
DEBUG; the CLI wires `--debug` to a stderr handler. No behavioural change otherwise.

### Gap: YouTube (`play youtube`)

Requires resolving a YouTube URL to a streamable URI (external resolver/yt-dlp-style).
Out of scope for the core lib; could live behind an optional extra. Lowest priority.

---

## Suggested milestones

1. **CLI parity for what's already backed** — wire remaining queue/grouping/favorites
   command variants around the existing lib helpers.
2. **Grouping** — `join` / `unjoin` / party / ungroup-all (high user value, low SOAP risk).
3. **Scenes** — snapshot/restore model over existing methods.
4. **`--debug` SOAP tracing** + CLI `config` store.
5. **YouTube** (optional extra, lowest priority).
