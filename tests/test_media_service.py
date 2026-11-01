"""Tests for MediaService discovery and stream aggregation."""

from unittest.mock import MagicMock
import pytest
from media_aggregator.models import MediaItem, MediaType, Quality, StreamSource, UserSettings
from media_aggregator.services.media_service import MediaService
from media_aggregator.storage import StorageManager


@pytest.fixture
def mock_cinemeta():
    mock = MagicMock()
    mock.search.return_value = [
        MediaItem(id="tt123", title="Matrix Test", type=MediaType.MOVIE, year="1999"),
        MediaItem(id="tt456", title="Matrix Reloaded Test", type=MediaType.MOVIE, year="2003"),
    ]
    mock.get_metadata.return_value = MediaItem(
        id="tt123",
        title="Matrix Test",
        type=MediaType.MOVIE,
        year="1999",
        synopsis="A simulated reality thriller.",
    )
    return mock


@pytest.fixture
def media_service(tmp_path, mock_cinemeta):
    storage = StorageManager(db_path=tmp_path / "test_media_service.db")
    service = MediaService(storage=storage, cinemeta=mock_cinemeta)
    return service


@pytest.mark.asyncio
async def test_media_service_search(media_service, mock_cinemeta):
    results = await media_service.search("Matrix")
    assert len(results) == 2
    assert results[0].title == "Matrix Test"
    mock_cinemeta.search.assert_called_once_with("Matrix", media_type=None)

    # Verify cached in DB
    cached = media_service.storage.get_media_item("tt123")
    assert cached is not None
    assert cached.title == "Matrix Test"


@pytest.mark.asyncio
async def test_media_service_get_details_cache_hit(media_service, mock_cinemeta):
    # Pre-populate cache
    item = MediaItem(
        id="tt999",
        title="Cached Item",
        type=MediaType.MOVIE,
        synopsis="Already in SQLite",
    )
    media_service.storage.save_media_item(item)

    retrieved = await media_service.get_details("tt999")
    assert retrieved is not None
    assert retrieved.title == "Cached Item"
    # Remote provider should not be contacted on full cache hit
    mock_cinemeta.get_metadata.assert_not_called()


@pytest.mark.asyncio
async def test_media_service_get_streams_filtering(media_service):
    # Mock stream provider
    mock_provider = MagicMock()
    mock_provider.get_streams.return_value = [
        StreamSource(
            id="s1",
            provider="torrentio",
            release_title="Matrix.4K.HDR",
            resolution="4K",
            quality=Quality.UHD_4K,
            seeders=50,
            size_bytes=10 * 1024 * 1024 * 1024,
            info_hash="aabbcc1122334455667788990011223344556677",
        ),
        StreamSource(
            id="s2",
            provider="torrentio",
            release_title="Matrix.1080p.CAM",
            resolution="CAM/SCR",
            quality=Quality.CAM_SCR,
            seeders=100,
            size_bytes=2 * 1024 * 1024 * 1024,
            info_hash="1122334455667788990011223344556677889900",
        ),
    ]

    media_service.registry.get_stream_providers = MagicMock(return_value=[mock_provider])

    # Settings: exclude CAM
    settings = UserSettings(min_seeders=1, exclude_cam=True)
    streams = await media_service.get_streams("tt123", settings=settings)

    # CAM should be excluded
    assert len(streams) == 1
    assert streams[0].resolution == "4K"
