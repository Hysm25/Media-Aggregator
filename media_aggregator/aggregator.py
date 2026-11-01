"""Concurrent stream aggregation, deduplication, filtering, and ranking engine."""

from __future__ import annotations

import concurrent.futures
from typing import Callable, Dict, List, Optional
from media_aggregator.models import MediaType, Quality, SourceType, StreamSource
from media_aggregator.providers.base import BaseProvider
from media_aggregator.providers.registry import ProviderRegistry
from media_aggregator.storage import StorageManager


class StreamAggregator:
    """Aggregates media streams across multiple providers concurrently with deduplication and sorting."""

    def __init__(
        self,
        registry: Optional[ProviderRegistry] = None,
        storage: Optional[StorageManager] = None,
        max_workers: int = 5,
    ):
        self.storage = storage or StorageManager()
        self.registry = registry or ProviderRegistry(storage=self.storage)
        self.max_workers = max_workers

    def fetch_streams_from_provider(
        self,
        provider: BaseProvider,
        media_type: MediaType,
        media_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> List[StreamSource]:
        """Safely fetch streams from a single provider."""
        try:
            return provider.get_streams(
                media_type=media_type,
                media_id=media_id,
                season=season,
                episode=episode,
            )
        except Exception:
            return []

    def aggregate_streams(
        self,
        media_type: MediaType,
        media_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        providers: Optional[List[BaseProvider]] = None,
        record_history: bool = True,
    ) -> List[StreamSource]:
        """Concurrently query all providers and aggregate all streams."""
        target_providers = providers or self.registry.get_stream_providers()
        all_streams: List[StreamSource] = []

        if not target_providers:
            return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_provider = {
                executor.submit(
                    self.fetch_streams_from_provider,
                    provider=p,
                    media_type=media_type,
                    media_id=media_id,
                    season=season,
                    episode=episode,
                ): p
                for p in target_providers
            }

            for future in concurrent.futures.as_completed(future_to_provider):
                try:
                    streams = future.result()
                    all_streams.extend(streams)
                except Exception:
                    pass

        # Deduplicate
        deduped = self.deduplicate_streams(all_streams)

        # Record in local history
        if record_history and deduped:
            try:
                self.storage.record_stream_sources(media_id=media_id, sources=deduped)
            except Exception:
                pass

        return deduped

    def deduplicate_streams(self, streams: List[StreamSource]) -> List[StreamSource]:
        """Merge identical streams across providers while retaining highest peer counts and trackers."""
        hash_map: Dict[str, StreamSource] = {}
        url_map: Dict[str, StreamSource] = {}
        unique_results: List[StreamSource] = []

        for s in streams:
            # 1. Deduplication by InfoHash (for torrents)
            if s.info_hash:
                norm_hash = s.info_hash.lower()
                if norm_hash in hash_map:
                    existing = hash_map[norm_hash]
                    self._merge_stream_data(existing, s)
                    continue
                else:
                    hash_map[norm_hash] = s
                    unique_results.append(s)
                    continue

            # 2. Deduplication by direct URL (for HTTP / Debrid)
            if s.url:
                norm_url = s.url.strip()
                if norm_url in url_map:
                    existing = url_map[norm_url]
                    self._merge_stream_data(existing, s)
                    continue
                else:
                    url_map[norm_url] = s
                    unique_results.append(s)
                    continue

            # Fallback for streams without hash or url
            unique_results.append(s)

        return unique_results

    def _merge_stream_data(self, primary: StreamSource, secondary: StreamSource) -> None:
        """Merge metadata from secondary duplicate into primary record."""
        # Merge provider names
        if secondary.provider not in primary.provider:
            primary.provider = f"{primary.provider} + {secondary.provider}"

        # Retain higher seeder count
        s1 = primary.seeders or 0
        s2 = secondary.seeders or 0
        primary.seeders = max(s1, s2) if (primary.seeders or secondary.seeders) else None

        # Retain size if primary was missing
        if not primary.size_bytes and secondary.size_bytes:
            primary.size_bytes = secondary.size_bytes
            primary.size_display = secondary.size_display

        # Merge trackers
        primary.trackers = list(dict.fromkeys(primary.trackers + secondary.trackers))

        # Merge HDR / Codecs / Audio
        primary.codecs = list(dict.fromkeys(primary.codecs + secondary.codecs))
        primary.hdr = list(dict.fromkeys(primary.hdr + secondary.hdr))
        primary.audio = list(dict.fromkeys(primary.audio + secondary.audio))

    def filter_streams(
        self,
        streams: List[StreamSource],
        min_seeders: Optional[int] = None,
        max_size_bytes: Optional[int] = None,
        exclude_cam: bool = True,
        allowed_qualities: Optional[List[Quality]] = None,
        source_types: Optional[List[SourceType]] = None,
    ) -> List[StreamSource]:
        """Filter stream sources based on user preferences."""
        filtered = []

        for s in streams:
            # CAM / Screener exclusion
            if exclude_cam and s.quality == Quality.CAM_SCR:
                continue

            # Allowed qualities
            if allowed_qualities is not None and s.quality not in allowed_qualities:
                continue

            # Source types
            if source_types is not None and s.source_type not in source_types:
                continue

            # Minimum seeders (for torrents)
            if min_seeders is not None and s.is_torrent:
                if s.seeders is not None and s.seeders < min_seeders:
                    continue

            # Maximum size
            if max_size_bytes is not None and s.size_bytes:
                if s.size_bytes > max_size_bytes:
                    continue

            filtered.append(s)

        return filtered

    def sort_streams(
        self,
        streams: List[StreamSource],
        sort_by: str = "quality",
    ) -> List[StreamSource]:
        """Sort stream sources by quality, seeders, or size."""
        if sort_by == "seeders":
            return sorted(streams, key=lambda s: s.seeders or 0, reverse=True)

        if sort_by == "size_desc":
            return sorted(streams, key=lambda s: s.size_bytes or 0, reverse=True)

        if sort_by == "size_asc":
            return sorted(streams, key=lambda s: s.size_bytes or float("inf"))

        if sort_by == "source_type":
            # Debrid & HTTP direct streams first, then torrents sorted by seeders
            return sorted(
                streams,
                key=lambda s: (
                    0 if s.source_type in (SourceType.DEBRID, SourceType.HTTP) else 1,
                    -(s.quality.score),
                    -(s.seeders or 0),
                ),
            )

        # Default: Sort by Quality Score descending, then Seeders descending, then Size
        return sorted(
            streams,
            key=lambda s: (
                s.quality.score,
                s.seeders or 0,
                s.size_bytes or 0,
            ),
            reverse=True,
        )

    def group_by_quality(self, streams: List[StreamSource]) -> Dict[str, List[StreamSource]]:
        """Group streams into resolution categories (4K, 1080p, 720p, etc.)."""
        groups: Dict[str, List[StreamSource]] = {
            "4K": [],
            "1080p": [],
            "720p": [],
            "480p": [],
            "Other": [],
        }

        for s in streams:
            if s.quality == Quality.UHD_4K:
                groups["4K"].append(s)
            elif s.quality == Quality.FHD_1080P:
                groups["1080p"].append(s)
            elif s.quality == Quality.HD_720P:
                groups["720p"].append(s)
            elif s.quality == Quality.SD_480P:
                groups["480p"].append(s)
            else:
                groups["Other"].append(s)

        return groups
