"""Type-safe callback data structures for inline keyboard interactions."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class NavCallback(CallbackData, prefix="nav"):
    """Navigation callback (e.g., home, search, downloads, settings, admin)."""
    action: str


class SearchCallback(CallbackData, prefix="srch"):
    """Search pagination callback."""
    query: str
    page: int


class MediaCallback(CallbackData, prefix="med"):
    """Media item details and actions callback."""
    id: str
    action: str = "view"  # view, seasons, bookmark


class SeasonCallback(CallbackData, prefix="sn"):
    """Season selection callback."""
    id: str
    season: int


class EpisodeCallback(CallbackData, prefix="ep"):
    """Episode selection callback."""
    id: str
    season: int
    episode: int


class StreamCallback(CallbackData, prefix="st"):
    """Stream selection and action callback."""
    id: str
    season: int
    episode: int
    idx: int
    action: str = "view"  # view, dl, magnet


class DownloadCallback(CallbackData, prefix="dl"):
    """Download record management callback."""
    id: int
    action: str = "view"  # view, cancel, refresh


class SettingsCallback(CallbackData, prefix="cfg"):
    """User preference modification callback."""
    action: str  # view, set_quality, toggle_cam, set_seeds
    key: str = ""
    val: str = ""


class AddonCallback(CallbackData, prefix="adn"):
    """Add-on provider management callback."""
    action: str  # list, toggle, delete
    id: str = ""


class AdminCallback(CallbackData, prefix="adm"):
    """Admin dashboard actions callback."""
    action: str  # view, approve, revoke, stats, claim
    uid: int = 0
