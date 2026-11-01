"""Tests for SQLite persistent storage layer."""

import os
import tempfile
import pytest
from media_aggregator.models import (
    AddonConfig,
    DownloadStatus,
    EpisodeItem,
    MediaItem,
    MediaType,
    SourceType,
    StreamSource,
)
from media_aggregator.storage import StorageManager


@pytest.fixture
def temp_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        storage = StorageManager(db_path=db_path)
        yield storage


def test_default_addons_initialization(temp_storage):
    addons = temp_storage.get_addons()
    assert len(addons) >= 2
    ids = [a.id for a in addons]
    assert "com.linvo.cinemeta" in ids
    assert "com.stremio.torrentio.addon" in ids


def test_media_cache(temp_storage):
    item = MediaItem(
        id="tt1234567",
        title="Test Movie",
        type=MediaType.MOVIE,
        year="2022",
        genres=["Action", "Sci-Fi"],
        cast=["Actor A", "Actor B"],
        director="Director X",
        imdb_rating="8.5",
        synopsis="A thrilling science fiction adventure.",
        episodes=[
            EpisodeItem(id="tt1234567:1:1", season=1, episode=1, title="Pilot Episode"),
        ],
    )

    temp_storage.save_media_item(item)
    retrieved = temp_storage.get_media_item("tt1234567")
    assert retrieved is not None
    assert retrieved.id == "tt1234567"
    assert retrieved.title == "Test Movie"
    assert retrieved.genres == ["Action", "Sci-Fi"]
    assert len(retrieved.episodes) == 1
    assert retrieved.episodes[0].title == "Pilot Episode"


def test_stream_history(temp_storage):
    stream = StreamSource(
        id="test_stream_1",
        provider="Torrentio",
        title="Test Release 1080p",
        info_hash="3c86b78efa012a402c28712d8be282d813f1a279",
        resolution="1080p",
        seeders=50,
        size_display="2.5 GB",
    )

    temp_storage.record_stream_sources("tt1234567", [stream])
    history = temp_storage.get_stream_history("tt1234567")
    assert len(history) == 1
    assert history[0]["provider"] == "Torrentio"
    assert history[0]["seeders"] == 50
    assert history[0]["info_hash"] == "3c86b78efa012a402c28712d8be282d813f1a279"


def test_downloads_tracking(temp_storage):
    dl_id = temp_storage.create_download(
        media_id="tt1234567",
        media_title="Test Movie",
        source_type=SourceType.HTTP,
        target_url="https://example.com/movie.mp4",
        local_path="/tmp/movie.mp4",
    )
    assert dl_id > 0

    record = temp_storage.get_download(dl_id)
    assert record is not None
    assert record.status == DownloadStatus.PENDING

    # Update progress
    temp_storage.update_download(
        dl_id,
        status=DownloadStatus.DOWNLOADING,
        downloaded_bytes=500,
        total_bytes=1000,
        progress_percent=50.0,
        speed_bps=100.0,
    )

    updated = temp_storage.get_download(dl_id)
    assert updated.status == DownloadStatus.DOWNLOADING
    assert updated.downloaded_bytes == 500
    assert updated.progress_percent == 50.0

    # Complete
    temp_storage.update_download(dl_id, status=DownloadStatus.COMPLETED, completed=True)
    completed = temp_storage.get_download(dl_id)
    assert completed.status == DownloadStatus.COMPLETED
    assert completed.completed_at is not None

    # Delete
    deleted = temp_storage.delete_download(dl_id)
    assert deleted is True
    assert temp_storage.get_download(dl_id) is None


def test_addons_management(temp_storage):
    new_addon = AddonConfig(
        id="custom.addon",
        name="Custom Provider",
        manifest_url="https://custom.com/manifest.json",
        base_url="https://custom.com",
        enabled=True,
        priority=20,
    )
    temp_storage.save_addon(new_addon)
    addons = temp_storage.get_addons()
    assert any(a.id == "custom.addon" for a in addons)

    temp_storage.set_addon_enabled("custom.addon", False)
    active = temp_storage.get_addons(enabled_only=True)
    assert not any(a.id == "custom.addon" for a in active)

    temp_storage.delete_addon("custom.addon")
    assert not any(a.id == "custom.addon" for a in temp_storage.get_addons())


def test_bookmarks(temp_storage):
    item = MediaItem(id="tt999", title="Bookmarked Movie", type=MediaType.MOVIE, year="2020")
    temp_storage.add_bookmark(item)
    bms = temp_storage.get_bookmarks()
    assert len(bms) == 1
    assert bms[0]["media_id"] == "tt999"

    temp_storage.remove_bookmark("tt999")
    assert len(temp_storage.get_bookmarks()) == 0
