"""Programmatic Python API for discovering and controlling Sonos speakers."""

from .client import DEFAULT_TIMEOUT, SonosClient
from .didl import parse_favorites, parse_track_metadata, radio_metadata
from .discovery import SonosController, SonosSystem, discover
from .errors import AmbiguousSpeakerError, DiscoveryError, SonosifyError, SpeakerNotFoundError, UPnPError
from .events import EventSubscription, SonosEvent, parse_last_change, parse_notify_event
from .models import Favorite, Group, PlaybackState, Speaker, Track
from .spotify import SpotifyItem, parse_spotify_uri, spotify_metadata

__all__ = [
    "DEFAULT_TIMEOUT",
    "AmbiguousSpeakerError",
    "DiscoveryError",
    "EventSubscription",
    "Favorite",
    "Group",
    "PlaybackState",
    "SonosClient",
    "SonosController",
    "SonosEvent",
    "SonosSystem",
    "SonosifyError",
    "Speaker",
    "SpeakerNotFoundError",
    "SpotifyItem",
    "Track",
    "UPnPError",
    "discover",
    "parse_last_change",
    "parse_notify_event",
    "parse_favorites",
    "parse_spotify_uri",
    "parse_track_metadata",
    "radio_metadata",
    "spotify_metadata",
]
