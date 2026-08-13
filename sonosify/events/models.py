from enum import StrEnum
from typing import Annotated, ClassVar, Literal, NamedTuple

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from sonosify.didl import parse_track_metadata
from sonosify.models import Track


class EventService(StrEnum):
    ALARM_CLOCK = "alarm_clock"
    AUDIO_IN = "audio_in"
    AV_TRANSPORT = "av_transport"
    CONTENT_DIRECTORY = "content_directory"
    DEVICE_PROPERTIES = "device_properties"
    GROUP_MANAGEMENT = "group_management"
    GROUP_RENDERING_CONTROL = "group_rendering_control"
    HT_CONTROL = "ht_control"
    MUSIC_SERVICES = "music_services"
    QUEUE = "queue"
    RENDERER_CONNECTION_MANAGER = "renderer_connection_manager"
    RENDERING_CONTROL = "rendering_control"
    SERVER_CONNECTION_MANAGER = "server_connection_manager"
    SYSTEM_PROPERTIES = "system_properties"
    VIRTUAL_LINE_IN = "virtual_line_in"
    ZONE_GROUP_TOPOLOGY = "zone_group_topology"


class TransportState(StrEnum):
    STOPPED = "STOPPED"
    PLAYING = "PLAYING"
    TRANSITIONING = "TRANSITIONING"
    PAUSED_PLAYBACK = "PAUSED_PLAYBACK"
    PAUSED_RECORDING = "PAUSED_RECORDING"
    RECORDING = "RECORDING"
    NO_MEDIA_PRESENT = "NO_MEDIA_PRESENT"


class PlayMode(StrEnum):
    NORMAL = "NORMAL"
    REPEAT_ALL = "REPEAT_ALL"
    REPEAT_ONE = "REPEAT_ONE"
    SHUFFLE_NOREPEAT = "SHUFFLE_NOREPEAT"
    SHUFFLE = "SHUFFLE"
    SHUFFLE_REPEAT_ONE = "SHUFFLE_REPEAT_ONE"


type RawEventValues = dict[str, str]


class _TrackSource(NamedTuple):
    """Which LastChange variables a `Track`-typed field is assembled from."""

    field: str
    metadata: str
    uri: str
    duration: str = ""
    position: str = ""


type _TrackSources = tuple[_TrackSource, ...]


def _number(value: object) -> object:
    if not isinstance(value, str):
        return value
    return int(value) if value.lstrip("-").isdigit() else None


def _flag(value: object) -> object:
    if not isinstance(value, str):
        return value
    return {"1": True, "true": True, "0": False, "false": False}.get(value.casefold())


def _csv(value: object) -> object:
    if not isinstance(value, str):
        return value
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _enum_or_none[E: StrEnum](enum: type[E]) -> BeforeValidator:
    """UPnP players emit values outside the documented range; never reject them."""

    def coerce(value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            return enum(value)
        except ValueError:
            return None

    return BeforeValidator(coerce)


type _Number = Annotated[int | None, BeforeValidator(_number)]
type _Flag = Annotated[bool | None, BeforeValidator(_flag)]
type _CSV = Annotated[tuple[str, ...], BeforeValidator(_csv)]
type _State = Annotated[TransportState | None, _enum_or_none(TransportState)]
type _PlayMode = Annotated[PlayMode | None, _enum_or_none(PlayMode)]


class SonosEvent(BaseModel):
    """One UPnP NOTIFY from one service.

    Subclasses map the documented state variables of their service onto typed
    fields via their UPnP names; ``values`` always keeps the full raw payload,
    including variables that have no typed field.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    event_path: ClassVar[str] = ""
    track_sources: ClassVar[_TrackSources] = ()

    service: str
    values: RawEventValues = {}
    sequence: int | None = None
    sid: str = ""

    @model_validator(mode="before")
    @classmethod
    def _compose_tracks(cls, data: object) -> object:
        if not cls.track_sources or not isinstance(data, dict):
            return data
        values = data.get("values") or {}
        composed = {
            source.field: _track(values, source) for source in cls.track_sources
        }
        return composed | data


class UnknownSonosEvent(SonosEvent):
    """Fallback for a service this library does not model."""


class SubscriptionLost(SonosEvent):
    """The player stopped accepting renewals for ``affected_services``.

    Emitted by the subscription itself rather than by the player: UPnP has no
    disconnect notification, so a speaker that reboots or leaves the network
    would otherwise just go quiet. The subscription keeps retrying and follows
    up with `SubscriptionRestored`.
    """

    service: Literal["subscription_lost"] = "subscription_lost"
    affected_services: tuple[EventService, ...] = ()
    error: str = ""


class SubscriptionRestored(SonosEvent):
    """Renewal succeeded again for every service after a `SubscriptionLost`.

    Events emitted while the player was unreachable are lost for good; treat
    this as a cue to re-read the state you care about.
    """

    service: Literal["subscription_restored"] = "subscription_restored"
    affected_services: tuple[EventService, ...] = ()


class AlarmClockEvent(SonosEvent):
    event_path: ClassVar[str] = "/AlarmClock/Event"

    service: Literal[EventService.ALARM_CLOCK] = EventService.ALARM_CLOCK
    alarm_list_version: str = Field("", alias="AlarmListVersion")
    daily_index_refresh_time: str = Field("", alias="DailyIndexRefreshTime")
    time_zone: str = Field("", alias="TimeZone")
    time_server: str = Field("", alias="TimeServer")
    time_generation: _Number = Field(None, alias="TimeGeneration")
    time_format: str = Field("", alias="TimeFormat")
    date_format: str = Field("", alias="DateFormat")


class AudioInEvent(SonosEvent):
    event_path: ClassVar[str] = "/AudioIn/Event"

    service: Literal[EventService.AUDIO_IN] = EventService.AUDIO_IN
    audio_input_name: str = Field("", alias="AudioInputName")
    icon: str = Field("", alias="Icon")
    line_in_connected: _Flag = Field(None, alias="LineInConnected")
    left_line_in_level: _Number = Field(None, alias="LeftLineInLevel")
    right_line_in_level: _Number = Field(None, alias="RightLineInLevel")
    playing: _Flag = Field(None, alias="Playing")


class AVTransportEvent(SonosEvent):
    event_path: ClassVar[str] = "/MediaRenderer/AVTransport/Event"
    track_sources: ClassVar[_TrackSources] = (
        _TrackSource(
            "track",
            "CurrentTrackMetaData",
            "CurrentTrackURI",
            duration="CurrentTrackDuration",
            position="CurrentTrack",
        ),
        _TrackSource("next_track", "NextTrackMetaData", "NextTrackURI"),
        _TrackSource(
            "enqueued_track", "EnqueuedTransportURIMetaData", "EnqueuedTransportURI"
        ),
    )

    service: Literal[EventService.AV_TRANSPORT] = EventService.AV_TRANSPORT
    transport_state: _State = Field(None, alias="TransportState")
    transport_status: str = Field("", alias="TransportStatus")
    transport_actions: _CSV = Field((), alias="CurrentTransportActions")
    transport_play_speed: str = Field("", alias="TransportPlaySpeed")
    play_mode: _PlayMode = Field(None, alias="CurrentPlayMode")
    valid_play_modes: _CSV = Field((), alias="CurrentValidPlayModes")
    crossfade: _Flag = Field(None, alias="CurrentCrossfadeMode")
    number_of_tracks: _Number = Field(None, alias="NumberOfTracks")
    current_track: _Number = Field(None, alias="CurrentTrack")
    current_section: _Number = Field(None, alias="CurrentSection")
    track: Track | None = None
    next_track: Track | None = None
    enqueued_track: Track | None = None
    enqueued_transport_uri: str = Field("", alias="EnqueuedTransportURI")
    av_transport_uri: str = Field("", alias="AVTransportURI")
    next_av_transport_uri: str = Field("", alias="NextAVTransportURI")
    media_duration: str = Field("", alias="CurrentMediaDuration")
    playback_storage_medium: str = Field("", alias="PlaybackStorageMedium")
    alarm_running: _Flag = Field(None, alias="AlarmRunning")
    snooze_running: _Flag = Field(None, alias="SnoozeRunning")
    restart_pending: _Flag = Field(None, alias="RestartPending")
    sleep_timer_generation: _Number = Field(None, alias="SleepTimerGeneration")
    direct_control_client_id: str = Field("", alias="DirectControlClientID")
    direct_control_account_id: str = Field("", alias="DirectControlAccountID")
    direct_control_is_suspended: _Flag = Field(None, alias="DirectControlIsSuspended")


class ContentDirectoryEvent(SonosEvent):
    event_path: ClassVar[str] = "/MediaServer/ContentDirectory/Event"

    service: Literal[EventService.CONTENT_DIRECTORY] = EventService.CONTENT_DIRECTORY
    system_update_id: _Number = Field(None, alias="SystemUpdateID")
    container_update_ids: _CSV = Field((), alias="ContainerUpdateIDs")
    favorites_update_id: str = Field("", alias="FavoritesUpdateID")
    favorite_presets_update_id: str = Field("", alias="FavoritePresetsUpdateID")
    saved_queues_update_id: str = Field("", alias="SavedQueuesUpdateID")
    share_list_update_id: str = Field("", alias="ShareListUpdateID")
    radio_favorites_update_id: str = Field("", alias="RadioFavoritesUpdateID")
    radio_location_update_id: str = Field("", alias="RadioLocationUpdateID")
    recently_played_update_id: str = Field("", alias="RecentlyPlayedUpdateID")
    user_radio_update_id: str = Field("", alias="UserRadioUpdateID")
    share_index_in_progress: _Flag = Field(None, alias="ShareIndexInProgress")
    share_index_last_error: str = Field("", alias="ShareIndexLastError")
    browseable: _Flag = Field(None, alias="Browseable")


class DevicePropertiesEvent(SonosEvent):
    event_path: ClassVar[str] = "/DeviceProperties/Event"

    service: Literal[EventService.DEVICE_PROPERTIES] = EventService.DEVICE_PROPERTIES
    zone_name: str = Field("", alias="ZoneName")
    active_zone_id: str = Field("", alias="ActiveZoneID")
    eth_link: _Flag = Field(None, alias="EthLink")
    icon: str = Field("", alias="Icon")
    configuration: str = Field("", alias="Configuration")
    invisible: _Flag = Field(None, alias="Invisible")
    is_zone_bridge: _Flag = Field(None, alias="IsZoneBridge")
    is_idle: _Flag = Field(None, alias="IsIdle")
    more_info: str = Field("", alias="MoreInfo")
    air_play_enabled: _Flag = Field(None, alias="AirPlayEnabled")
    supports_audio_in: _Flag = Field(None, alias="SupportsAudioIn")
    supports_audio_clip: _Flag = Field(None, alias="SupportsAudioClip")
    channel_map_set: str = Field("", alias="ChannelMapSet")
    ht_sat_chan_map_set: str = Field("", alias="HTSatChanMapSet")
    ht_freq: _Number = Field(None, alias="HTFreq")
    ht_bonded_zone_commit_state: _Number = Field(None, alias="HTBondedZoneCommitState")
    orientation: _Number = Field(None, alias="Orientation")
    last_changed_play_state: str = Field("", alias="LastChangedPlayState")
    room_calibration_state: _Number = Field(None, alias="RoomCalibrationState")
    available_room_calibration: str = Field("", alias="AvailableRoomCalibration")
    tv_configuration_error: _Flag = Field(None, alias="TVConfigurationError")
    hdmi_cec_available: _Flag = Field(None, alias="HdmiCecAvailable")
    wireless_mode: _Number = Field(None, alias="WirelessMode")
    wireless_leaf_only: _Flag = Field(None, alias="WirelessLeafOnly")
    wifi_enabled: _Flag = Field(None, alias="WifiEnabled")
    has_configured_ssid: _Flag = Field(None, alias="HasConfiguredSSID")
    behind_wifi_extender: _Number = Field(None, alias="BehindWifiExtender")
    channel_freq: _Number = Field(None, alias="ChannelFreq")
    config_mode: str = Field("", alias="ConfigMode")
    mic_enabled: _Flag = Field(None, alias="MicEnabled")
    secure_reg_state: _Number = Field(None, alias="SecureRegState")
    voice_config_state: _Number = Field(None, alias="VoiceConfigState")
    settings_replication_state: str = Field("", alias="SettingsReplicationState")


class GroupManagementEvent(SonosEvent):
    event_path: ClassVar[str] = "/GroupManagement/Event"

    service: Literal[EventService.GROUP_MANAGEMENT] = EventService.GROUP_MANAGEMENT
    group_coordinator_is_local: _Flag = Field(None, alias="GroupCoordinatorIsLocal")
    local_group_uuid: str = Field("", alias="LocalGroupUUID")
    virtual_line_in_group_id: str = Field("", alias="VirtualLineInGroupID")
    source_area_ids: str = Field("", alias="SourceAreaIds")
    reset_volume_after: _Flag = Field(None, alias="ResetVolumeAfter")
    volume_av_transport_uri: str = Field("", alias="VolumeAVTransportURI")


class GroupRenderingControlEvent(SonosEvent):
    event_path: ClassVar[str] = "/MediaRenderer/GroupRenderingControl/Event"

    service: Literal[EventService.GROUP_RENDERING_CONTROL] = (
        EventService.GROUP_RENDERING_CONTROL
    )
    group_volume: _Number = Field(None, alias="GroupVolume")
    group_muted: _Flag = Field(None, alias="GroupMute")
    group_volume_changeable: _Flag = Field(None, alias="GroupVolumeChangeable")


class HTControlEvent(SonosEvent):
    event_path: ClassVar[str] = "/HTControl/Event"

    service: Literal[EventService.HT_CONTROL] = EventService.HT_CONTROL
    ir_repeater_state: str = Field("", alias="IRRepeaterState")
    remote_configured: _Flag = Field(None, alias="RemoteConfigured")
    tos_link_connected: _Flag = Field(None, alias="TOSLinkConnected")


class MusicServicesEvent(SonosEvent):
    event_path: ClassVar[str] = "/MusicServices/Event"

    service: Literal[EventService.MUSIC_SERVICES] = EventService.MUSIC_SERVICES
    service_list_version: str = Field("", alias="ServiceListVersion")


class QueueEvent(SonosEvent):
    event_path: ClassVar[str] = "/MediaRenderer/Queue/Event"

    service: Literal[EventService.QUEUE] = EventService.QUEUE
    update_id: _Number = Field(None, alias="UpdateID")
    queue_owner_id: str = Field("", alias="QueueOwnerID")
    queue_owner_context: str = Field("", alias="QueueOwnerContext")
    curated: _Flag = Field(None, alias="Curated")


class RendererConnectionManagerEvent(SonosEvent):
    event_path: ClassVar[str] = "/MediaRenderer/ConnectionManager/Event"

    service: Literal[EventService.RENDERER_CONNECTION_MANAGER] = (
        EventService.RENDERER_CONNECTION_MANAGER
    )
    source_protocol_info: _CSV = Field((), alias="SourceProtocolInfo")
    sink_protocol_info: _CSV = Field((), alias="SinkProtocolInfo")
    current_connection_ids: _CSV = Field((), alias="CurrentConnectionIDs")


class RenderingControlEvent(SonosEvent):
    """Master-channel values; per-channel ones stay in ``values`` as ``Volume:LF``."""

    event_path: ClassVar[str] = "/MediaRenderer/RenderingControl/Event"

    service: Literal[EventService.RENDERING_CONTROL] = EventService.RENDERING_CONTROL
    volume: _Number = Field(None, alias="Volume")
    muted: _Flag = Field(None, alias="Mute")
    bass: _Number = Field(None, alias="Bass")
    treble: _Number = Field(None, alias="Treble")
    loudness: _Flag = Field(None, alias="Loudness")
    output_fixed: _Flag = Field(None, alias="OutputFixed")
    headphone_connected: _Flag = Field(None, alias="HeadphoneConnected")
    night_mode: _Flag = Field(None, alias="NightMode")
    dialog_level: _Flag = Field(None, alias="DialogLevel")
    speech_enhance_enabled: _Flag = Field(None, alias="SpeechEnhanceEnabled")
    sub_enabled: _Flag = Field(None, alias="SubEnabled")
    sub_gain: _Number = Field(None, alias="SubGain")
    sub_crossover: _Number = Field(None, alias="SubCrossover")
    sub_polarity: _Number = Field(None, alias="SubPolarity")
    surround_enabled: _Flag = Field(None, alias="SurroundEnabled")
    surround_mode: _Number = Field(None, alias="SurroundMode")
    surround_level: _Number = Field(None, alias="SurroundLevel")
    music_surround_level: _Number = Field(None, alias="MusicSurroundLevel")
    height_channel_level: _Number = Field(None, alias="HeightChannelLevel")
    audio_delay: _Number = Field(None, alias="AudioDelay")
    audio_delay_left_rear: _Number = Field(None, alias="AudioDelayLeftRear")
    audio_delay_right_rear: _Number = Field(None, alias="AudioDelayRightRear")
    speaker_size: _Number = Field(None, alias="SpeakerSize")
    trueplay_enabled: _Flag = Field(None, alias="SonarEnabled")
    trueplay_calibration_available: _Flag = Field(
        None, alias="SonarCalibrationAvailable"
    )
    preset_name_list: str = Field("", alias="PresetNameList")


class ServerConnectionManagerEvent(SonosEvent):
    event_path: ClassVar[str] = "/MediaServer/ConnectionManager/Event"

    service: Literal[EventService.SERVER_CONNECTION_MANAGER] = (
        EventService.SERVER_CONNECTION_MANAGER
    )
    source_protocol_info: _CSV = Field((), alias="SourceProtocolInfo")
    sink_protocol_info: _CSV = Field((), alias="SinkProtocolInfo")
    current_connection_ids: _CSV = Field((), alias="CurrentConnectionIDs")


class SystemPropertiesEvent(SonosEvent):
    event_path: ClassVar[str] = "/SystemProperties/Event"

    service: Literal[EventService.SYSTEM_PROPERTIES] = EventService.SYSTEM_PROPERTIES
    customer_id: str = Field("", alias="CustomerID")
    update_id: _Number = Field(None, alias="UpdateID")
    update_idx: _Number = Field(None, alias="UpdateIDX")
    voice_update_id: _Number = Field(None, alias="VoiceUpdateID")
    third_party_hash: str = Field("", alias="ThirdPartyHash")


class VirtualLineInEvent(SonosEvent):
    event_path: ClassVar[str] = "/MediaRenderer/VirtualLineIn/Event"
    track_sources: ClassVar[_TrackSources] = (
        _TrackSource("track", "CurrentTrackMetaData", "CurrentTrackURI"),
    )

    service: Literal[EventService.VIRTUAL_LINE_IN] = EventService.VIRTUAL_LINE_IN
    transport_state: _State = Field(None, alias="TransportState")
    track: Track | None = None
    current_track_uri: str = Field("", alias="CurrentTrackURI")
    enqueued_transport_uri: str = Field("", alias="EnqueuedTransportURI")


class ZoneGroupTopologyEvent(SonosEvent):
    event_path: ClassVar[str] = "/ZoneGroupTopology/Event"

    service: Literal[EventService.ZONE_GROUP_TOPOLOGY] = (
        EventService.ZONE_GROUP_TOPOLOGY
    )
    zone_group_state: str = Field("", alias="ZoneGroupState")
    zone_group_id: str = Field("", alias="ZoneGroupID")
    zone_group_name: str = Field("", alias="ZoneGroupName")
    zone_player_uuids_in_group: _CSV = Field((), alias="ZonePlayerUUIDsInGroup")
    available_software_update: str = Field("", alias="AvailableSoftwareUpdate")
    alarm_run_sequence: str = Field("", alias="AlarmRunSequence")
    third_party_media_servers: str = Field("", alias="ThirdPartyMediaServersX")
    muse_household_id: str = Field("", alias="MuseHouseholdId")
    areas_update_id: str = Field("", alias="AreasUpdateID")
    source_areas_update_id: str = Field("", alias="SourceAreasUpdateID")
    net_settings_update_id: str = Field("", alias="NetsettingsUpdateID")


_EVENT_TYPES: dict[EventService, type[SonosEvent]] = {
    EventService.ALARM_CLOCK: AlarmClockEvent,
    EventService.AUDIO_IN: AudioInEvent,
    EventService.AV_TRANSPORT: AVTransportEvent,
    EventService.CONTENT_DIRECTORY: ContentDirectoryEvent,
    EventService.DEVICE_PROPERTIES: DevicePropertiesEvent,
    EventService.GROUP_MANAGEMENT: GroupManagementEvent,
    EventService.GROUP_RENDERING_CONTROL: GroupRenderingControlEvent,
    EventService.HT_CONTROL: HTControlEvent,
    EventService.MUSIC_SERVICES: MusicServicesEvent,
    EventService.QUEUE: QueueEvent,
    EventService.RENDERER_CONNECTION_MANAGER: RendererConnectionManagerEvent,
    EventService.RENDERING_CONTROL: RenderingControlEvent,
    EventService.SERVER_CONNECTION_MANAGER: ServerConnectionManagerEvent,
    EventService.SYSTEM_PROPERTIES: SystemPropertiesEvent,
    EventService.VIRTUAL_LINE_IN: VirtualLineInEvent,
    EventService.ZONE_GROUP_TOPOLOGY: ZoneGroupTopologyEvent,
}

ALL_SERVICES = tuple(_EVENT_TYPES)
DEFAULT_SERVICES = (EventService.AV_TRANSPORT, EventService.RENDERING_CONTROL)

_SERVICE_ALIASES = {
    "".join(character for character in service if character.isalnum()): service
    for service in _EVENT_TYPES
}


def normalize_service(service: str | EventService) -> EventService | None:
    """Resolve ``AVTransport``, ``av-transport``, ``av_transport`` to one member."""
    key = "".join(character for character in service if character.isalnum())
    return _SERVICE_ALIASES.get(key.casefold())


def require_service(service: str | EventService) -> EventService:
    normalized = normalize_service(service)
    if normalized is None:
        raise ValueError(f"unsupported event service: {service!r}")
    return normalized


def event_type(service: str | EventService) -> type[SonosEvent]:
    normalized = normalize_service(service)
    return UnknownSonosEvent if normalized is None else _EVENT_TYPES[normalized]


def event_path(service: str | EventService) -> str:
    return _EVENT_TYPES[require_service(service)].event_path


def _track(values: RawEventValues, source: _TrackSource) -> Track | None:
    metadata = values.get(source.metadata, "")
    if not metadata:
        return None
    return parse_track_metadata(
        metadata,
        uri=values.get(source.uri, ""),
        duration=values.get(source.duration, ""),
        position=_position(values.get(source.position)),
    )


def _position(value: str | None) -> int | None:
    number = _number(value)
    return number if isinstance(number, int) else None
