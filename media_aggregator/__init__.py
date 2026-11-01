"""Media Source Aggregator: Independent Stremio & Torrentio Stream Engine."""

__version__ = "1.0.0"

from media_aggregator.aggregator import StreamAggregator
from media_aggregator.downloader.manager import DownloadManager
from media_aggregator.models import MediaItem, MediaType, Quality, SourceType, StreamSource, SubtitleTrack
from media_aggregator.providers.cinemeta import CinemetaProvider
from media_aggregator.providers.generic import GenericStremioProvider
from media_aggregator.providers.registry import ProviderRegistry
from media_aggregator.providers.torrentio import TorrentioProvider
from media_aggregator.storage import StorageManager

__all__ = [
    "StreamAggregator",
    "DownloadManager",
    "StorageManager",
    "ProviderRegistry",
    "MediaItem",
    "MediaType",
    "StreamSource",
    "SubtitleTrack",
    "SourceType",
    "Quality",
    "CinemetaProvider",
    "TorrentioProvider",
    "GenericStremioProvider",
]
