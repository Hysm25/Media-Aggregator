"""Tests for StreamAggregator (concurrency, deduplication, filtering, sorting)."""

from unittest.mock import MagicMock
import pytest
from media_aggregator.aggregator import StreamAggregator
from media_aggregator.models import MediaType, Quality, SourceType, StreamSource
from media_aggregator.storage import StorageManager


def make_dummy_stream(
    stream_id: str,
    provider: str,
    info_hash: str = None,
    url: str = None,
    quality: Quality = Quality.FHD_1080P,
    seeders: int = 10,
    size_bytes: int = 2000000000,
    trackers: list = None,
) -> StreamSource:
    return StreamSource(
        id=stream_id,
        provider=provider,
        title=f"Movie.{quality.value}",
        info_hash=info_hash,
        url=url,
        quality=quality,
        resolution=quality.value,
        source_type=SourceType.TORRENT if info_hash else SourceType.HTTP,
        seeders=seeders,
        size_bytes=size_bytes,
        trackers=trackers or [],
    )


def test_deduplication_by_info_hash():
    aggregator = StreamAggregator()

    s1 = make_dummy_stream(
        stream_id="1",
        provider="Torrentio",
        info_hash="3c86b78efa012a402c28712d8be282d813f1a279",
        seeders=25,
        trackers=["udp://tracker1:1337"],
    )
    s2 = make_dummy_stream(
        stream_id="2",
        provider="MediaFusion",
        info_hash="3C86B78EFA012A402C28712D8BE282D813F1A279",  # Upper case
        seeders=45,
        trackers=["udp://tracker2:1337"],
    )

    deduped = aggregator.deduplicate_streams([s1, s2])
    assert len(deduped) == 1
    merged = deduped[0]
    assert merged.seeders == 45  # Highest seeders kept
    assert "Torrentio" in merged.provider and "MediaFusion" in merged.provider
    assert "udp://tracker1:1337" in merged.trackers
    assert "udp://tracker2:1337" in merged.trackers


def test_deduplication_by_url():
    aggregator = StreamAggregator()

    s1 = make_dummy_stream(
        stream_id="u1",
        provider="ProviderA",
        url="https://cdn.example.com/movie.mp4",
        quality=Quality.HD_720P,
    )
    s2 = make_dummy_stream(
        stream_id="u2",
        provider="ProviderB",
        url="https://cdn.example.com/movie.mp4",
        quality=Quality.HD_720P,
    )

    deduped = aggregator.deduplicate_streams([s1, s2])
    assert len(deduped) == 1
    assert "ProviderA" in deduped[0].provider and "ProviderB" in deduped[0].provider


def test_filtering():
    aggregator = StreamAggregator()

    streams = [
        make_dummy_stream("1", "T", info_hash="hash1", quality=Quality.UHD_4K, seeders=100, size_bytes=10 * 1000**3),
        make_dummy_stream("2", "T", info_hash="hash2", quality=Quality.FHD_1080P, seeders=5, size_bytes=2 * 1000**3),
        make_dummy_stream("3", "T", info_hash="hash3", quality=Quality.CAM_SCR, seeders=80, size_bytes=1 * 1000**3),
    ]

    # Exclude CAM
    f1 = aggregator.filter_streams(streams, exclude_cam=True)
    assert len(f1) == 2
    assert not any(s.quality == Quality.CAM_SCR for s in f1)

    # Min seeders filter
    f2 = aggregator.filter_streams(streams, min_seeders=10, exclude_cam=False)
    assert len(f2) == 2
    assert not any(s.seeders < 10 for s in f2)

    # Max size filter (max 5 GB)
    f3 = aggregator.filter_streams(streams, max_size_bytes=5 * 1000**3, exclude_cam=False)
    assert len(f3) == 2
    assert not any(s.size_bytes > 5 * 1000**3 for s in f3)

    # Allowed quality filter
    f4 = aggregator.filter_streams(streams, allowed_qualities=[Quality.UHD_4K])
    assert len(f4) == 1
    assert f4[0].quality == Quality.UHD_4K


def test_sorting():
    aggregator = StreamAggregator()

    s_4k = make_dummy_stream("4k", "T", info_hash="h1", quality=Quality.UHD_4K, seeders=10, size_bytes=15000)
    s_1080 = make_dummy_stream("1080", "T", info_hash="h2", quality=Quality.FHD_1080P, seeders=100, size_bytes=5000)
    s_720 = make_dummy_stream("720", "T", info_hash="h3", quality=Quality.HD_720P, seeders=50, size_bytes=2000)
    s_http = make_dummy_stream("http", "H", url="https://http.com", quality=Quality.FHD_1080P, seeders=0, size_bytes=3000)

    # Sort by quality (4K first, then 1080p, then 720p)
    by_qual = aggregator.sort_streams([s_720, s_4k, s_1080], sort_by="quality")
    assert by_qual[0].quality == Quality.UHD_4K
    assert by_qual[1].quality == Quality.FHD_1080P
    assert by_qual[2].quality == Quality.HD_720P

    # Sort by seeders
    by_seeds = aggregator.sort_streams([s_4k, s_1080, s_720], sort_by="seeders")
    assert by_seeds[0].seeders == 100
    assert by_seeds[1].seeders == 50
    assert by_seeds[2].seeders == 10

    # Sort by size descending
    by_size = aggregator.sort_streams([s_4k, s_1080, s_720], sort_by="size_desc")
    assert by_size[0].size_bytes == 15000

    # Sort by size ascending
    by_size_asc = aggregator.sort_streams([s_4k, s_1080, s_720], sort_by="size_asc")
    assert by_size_asc[0].size_bytes == 2000

    # Sort by source_type (HTTP first)
    by_type = aggregator.sort_streams([s_4k, s_http], sort_by="source_type")
    assert by_type[0].source_type == SourceType.HTTP


def test_group_by_quality():
    aggregator = StreamAggregator()
    s_4k = make_dummy_stream("1", "T", quality=Quality.UHD_4K)
    s_1080 = make_dummy_stream("2", "T", quality=Quality.FHD_1080P)

    groups = aggregator.group_by_quality([s_4k, s_1080])
    assert len(groups["4K"]) == 1
    assert len(groups["1080p"]) == 1
    assert len(groups["720p"]) == 0
