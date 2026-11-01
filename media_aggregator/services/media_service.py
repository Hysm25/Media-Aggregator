"""Media discovery and stream aggregation application service."""

from __future__ import annotations

import asyncio
from typing import List, Optional
from media_aggregator.aggregator import StreamAggregator
from media_aggregator.models import MediaItem, MediaType, StreamSource, UserSettings
from media_aggregator.providers.cinemeta import CinemetaProvider
from media_aggregator.providers.registry import ProviderRegistry
from media_aggregator.storage import StorageManager


class MediaService:
    """Async business logic service for media search, details, and stream aggregation."""

    def __init__(
        self,
        storage: Optional[StorageManager] = None,
        cinemeta: Optional[CinemetaProvider] = None,
        registry: Optional[ProviderRegistry] = None,
    ):
        self.storage = storage or StorageManager()
        self.cinemeta = cinemeta or CinemetaProvider()
        self.registry = registry or ProviderRegistry(self.storage)
        self.aggregator = StreamAggregator()

    async def search(self, query: str, media_type: Optional[MediaType] = None) -> List[MediaItem]:
        """Search movies and TV series asynchronously."""
        def _search() -> List[MediaItem]:
            results = self.cinemeta.search(query, media_type=media_type)
            # Pre-cache retrieved items for fast detail lookups
            for item in results:
                self.storage.save_media_item(item)
            return results

        return await asyncio.to_thread(_search)

    async def get_details(self, media_id: str, media_type: Optional[MediaType] = None) -> Optional[MediaItem]:
        """Retrieve media metadata, checking local cache first then remote provider."""
        cached = self.storage.get_media_item(media_id)
        if cached and (cached.synopsis or cached.episodes):
            return cached

        def _fetch() -> Optional[MediaItem]:
            item = self.cinemeta.get_metadata(media_id, media_type=media_type)
            if item:
                self.storage.save_media_item(item)
            return item

        remote_item = await asyncio.to_thread(_fetch)
        return remote_item or cached

    async def get_streams(
        self,
        media_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        settings: Optional[UserSettings] = None,
    ) -> List[StreamSource]:
        """Query active stream add-ons and filter according to user settings."""
        providers = self.registry.get_stream_providers()
        if not providers:
            return []

        # Determine media type from ID or cache
        media_type = MediaType.MOVIE
        if season is not None and episode is not None:
            media_type = MediaType.SERIES
        else:
            cached = self.storage.get_media_item(media_id)
            if cached and cached.type == MediaType.SERIES:
                media_type = MediaType.SERIES

        def _aggregate() -> List[StreamSource]:
            raw_streams = self.aggregator.aggregate_streams(
                providers=providers,
                media_id=media_id,
                media_type=media_type,
                season=season,
                episode=episode,
            )

            # Record in SQLite history
            self.storage.record_stream_sources(media_id, raw_streams)

            # Apply user preferences if provided
            min_seeds = settings.min_seeders if settings else 1
            exclude_cam = settings.exclude_cam if settings else True
            max_size = (settings.max_size_gb * 1024 * 1024 * 1024) if settings and settings.max_size_gb else None
            sort_by = settings.sort_by if settings else "quality_size"

            filtered = self.aggregator.filter_streams(
                streams=raw_streams,
                min_seeders=min_seeds,
                exclude_cam=exclude_cam,
                max_size_bytes=int(max_size) if max_size else None,
            )

            return self.aggregator.sort_streams(filtered, sort_by=sort_by)

        return await asyncio.to_thread(_aggregate)
