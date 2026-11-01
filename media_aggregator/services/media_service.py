"""Media discovery and stream aggregation application service."""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional
from media_aggregator.aggregator import StreamAggregator
from media_aggregator.models import MediaItem, MediaType, StreamSource, UserSettings
from media_aggregator.providers.cinemeta import CinemetaProvider
from media_aggregator.providers.registry import ProviderRegistry
from media_aggregator.storage import StorageManager

logger = logging.getLogger("media_aggregator.services.media")


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
        """Search movies and TV series across active providers asynchronously."""
        def _search() -> List[MediaItem]:
            results: List[MediaItem] = []
            seen_ids = set()

            # 1. Primary search via Cinemeta discovery provider
            try:
                primary_items = self.cinemeta.search(query, media_type=media_type)
                for item in primary_items:
                    if item.id and item.id not in seen_ids:
                        seen_ids.add(item.id)
                        results.append(item)
                        self.storage.save_media_item(item)
            except Exception as e:
                logger.warning(f"Cinemeta search failed for '{query}': {e}")

            # 2. If anime requested, query active anime catalog providers
            if media_type == MediaType.ANIME:
                for provider in self.registry.get_active_providers():
                    if isinstance(provider, CinemetaProvider):
                        continue
                    if "kitsu" in provider.name.lower() or "anime" in provider.name.lower():
                        try:
                            anime_items = provider.search(query=query, media_type=MediaType.ANIME)
                            for item in anime_items:
                                if item.id and item.id not in seen_ids:
                                    seen_ids.add(item.id)
                                    results.append(item)
                                    self.storage.save_media_item(item)
                        except Exception as e:
                            logger.debug(f"Anime provider '{provider.name}' search failed for '{query}': {e}")

            return results

        return await asyncio.to_thread(_search)

    async def get_details(self, media_id: str, media_type: Optional[MediaType] = None) -> Optional[MediaItem]:
        """Retrieve media metadata, checking local cache first then remote providers."""
        cached = self.storage.get_media_item(media_id)
        if cached and (cached.synopsis or cached.episodes):
            return cached

        actual_type = media_type or (cached.type if cached else None)

        def _fetch() -> Optional[MediaItem]:
            # 1. Try primary Cinemeta provider
            try:
                item = self.cinemeta.get_metadata(media_id, media_type=actual_type)
                if item:
                    self.storage.save_media_item(item)
                    return item
            except Exception as e:
                logger.debug(f"Cinemeta get_metadata failed for {media_id}: {e}")

            # 2. Try any other active metadata providers (e.g. anime or custom add-ons)
            for provider in self.registry.get_metadata_providers(media_type=actual_type, media_id=media_id):
                if isinstance(provider, CinemetaProvider):
                    continue
                try:
                    item = provider.get_metadata(media_id=media_id, media_type=actual_type)
                    if item:
                        self.storage.save_media_item(item)
                        return item
                except Exception as e:
                    logger.debug(f"Provider '{provider.name}' get_metadata failed for {media_id}: {e}")

            return None

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
        # Determine media type from parameters or cache
        media_type = MediaType.MOVIE
        if season is not None and episode is not None and (season > 0 or episode > 0):
            media_type = MediaType.SERIES
        else:
            cached = self.storage.get_media_item(media_id)
            if cached and cached.type == MediaType.SERIES:
                media_type = MediaType.SERIES

        providers = self.registry.get_stream_providers(media_type=media_type, media_id=media_id)
        if not providers:
            return []

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
