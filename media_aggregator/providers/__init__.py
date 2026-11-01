"""Provider interfaces and implementations for media metadata and stream resolution."""

from media_aggregator.providers.base import BaseProvider
from media_aggregator.providers.cinemeta import CinemetaProvider
from media_aggregator.providers.generic import GenericStremioProvider
from media_aggregator.providers.registry import ProviderRegistry
from media_aggregator.providers.torrentio import TorrentioProvider

__all__ = [
    "BaseProvider",
    "CinemetaProvider",
    "GenericStremioProvider",
    "TorrentioProvider",
    "ProviderRegistry",
]
