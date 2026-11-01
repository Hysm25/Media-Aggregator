"""Tests for asynchronous download service, background tasks, and restart recovery."""

import asyncio
from unittest.mock import MagicMock, patch
import pytest
from media_aggregator.models import DownloadStatus, Quality, SourceType, StreamSource
from media_aggregator.services.download_service import DownloadService
from media_aggregator.storage import StorageManager


@pytest.fixture
def download_service(tmp_path):
    storage = StorageManager(db_path=tmp_path / "test_dl_service.db")
    dl_dir = tmp_path / "downloads"
    service = DownloadService(storage=storage, download_dir=dl_dir)
    return service


@pytest.mark.asyncio
async def test_recover_interrupted_downloads(download_service):
    # Seed interrupted downloads
    rec1 = download_service.storage.create_download(
        media_id="tt1",
        media_title="Movie 1",
        source_type=SourceType.HTTP,
        target_url="http://example.com/1.mp4",
        user_id=1,
    )
    download_service.storage.update_download(rec1, status=DownloadStatus.DOWNLOADING)

    rec2 = download_service.storage.create_download(
        media_id="tt2",
        media_title="Movie 2",
        source_type=SourceType.HTTP,
        target_url="http://example.com/2.mp4",
        user_id=1,
    )
    download_service.storage.update_download(rec2, status=DownloadStatus.PENDING)

    recovered = await download_service.recover_interrupted_downloads()
    assert recovered == 2

    # Verify both are marked CANCELLED
    assert download_service.storage.get_download(rec1).status == DownloadStatus.CANCELLED
    assert download_service.storage.get_download(rec2).status == DownloadStatus.CANCELLED


@pytest.mark.asyncio
async def test_start_torrent_download_dispatch(download_service):
    stream = StreamSource(
        id="t1",
        provider="torrentio",
        release_title="Test.Torrent.Release",
        info_hash="aabbccddeeff00112233445566778899aabbccdd",
        source_type=SourceType.TORRENT,
        size_bytes=1000,
    )

    completed_called = asyncio.Event()

    async def on_completed(rec):
        completed_called.set()

    rec = await download_service.start_download(
        stream=stream,
        media_id="tt_torrent",
        media_title="Torrent Title",
        user_id=123,
        on_completed=on_completed,
    )

    assert rec.status in (DownloadStatus.COMPLETED, DownloadStatus.DOWNLOADING)
    assert rec.user_id == 123
    assert rec.local_path is not None
    assert rec.local_path.endswith(".magnet")

    await asyncio.wait_for(completed_called.wait(), timeout=2.0)


@pytest.mark.asyncio
async def test_start_http_download_and_complete(download_service):
    stream = StreamSource(
        id="h1",
        provider="debrid",
        release_title="Test.HTTP.Stream",
        url="http://example.com/movie.mp4",
        source_type=SourceType.HTTP,
        size_bytes=5000,
    )

    completed_called = asyncio.Event()

    async def on_completed(rec):
        completed_called.set()

    # Mock HTTPDownloader.download_file so it doesn't make real network calls
    with patch("media_aggregator.services.download_service.HTTPDownloader") as mock_downloader_cls:
        mock_instance = MagicMock()
        mock_instance.download_file.return_value = "/tmp/downloads/movie.mp4"
        mock_downloader_cls.return_value = mock_instance

        rec = await download_service.start_download(
            stream=stream,
            media_id="tt_http",
            media_title="HTTP Title",
            user_id=456,
            on_completed=on_completed,
        )

        assert rec.id is not None
        assert rec.status == DownloadStatus.DOWNLOADING

        # Wait for worker completion
        await asyncio.wait_for(completed_called.wait(), timeout=3.0)

        finished_rec = await download_service.get_download(rec.id)
        assert finished_rec.status == DownloadStatus.COMPLETED
        assert finished_rec.local_path == "/tmp/downloads/movie.mp4"
