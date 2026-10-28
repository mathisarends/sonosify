from enum import StrEnum as _StrEnum


class _UPnPService(_StrEnum):
    AV_TRANSPORT = "MediaRenderer/AVTransport"
    RENDERING_CONTROL = "MediaRenderer/RenderingControl"
    GROUP_RENDERING_CONTROL = "MediaRenderer/GroupRenderingControl"
    CONTENT_DIRECTORY = "MediaServer/ContentDirectory"
    DEVICE_PROPERTIES = "DeviceProperties"
    ZONE_GROUP_TOPOLOGY = "ZoneGroupTopology"

    @property
    def control_path(self) -> str:
        return f"/{self.value}/Control"

    @property
    def urn(self) -> str:
        name = self.value.rsplit("/", 1)[-1]
        return f"urn:schemas-upnp-org:service:{name}:1"


class _ControlNamespace(_StrEnum):
    AUDIO_CLIP = "audioClip:1"
    PLAYER_VOLUME = "playerVolume:1"


def _duck_options(duration_millis: int | None) -> dict[str, object]:
    if duration_millis is None:
        return {}
    if not 1 <= duration_millis <= 60_000:
        raise ValueError("duration_millis must be between 1 and 60000")
    return {"durationMillis": duration_millis}
