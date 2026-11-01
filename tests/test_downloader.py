"""Tests for downloader engine (HTTP chunked range downloader, torrent dispatcher)."""

import hashlib
import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest
from media_aggregator.downloader.http import HTTPDownloader
from media_aggregator.downloader.manager import DownloadManager
from media_aggregator.downloader.torrent import TorrentDownloader
from media_aggregator.models import (
    DownloadStatus,
    Quality,
    SourceType,
    StreamSource,
)
from media_aggregator.storage import StorageManager


def test_http_downloader_basic():
    test_content = b"Hello, this is a simulated media stream content for testing!"
    sha256_hash = hashlib.sha256(test_content).hexdigest()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(len(test_content))}
    mock_resp.iter_content.return_value = [test_content[:20], test_content[20:]]

    downloader = HTTPDownloader()

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = os.path.join(tmpdir, "video.mp4")
        with patch.object(downloader.session, "get", return_value=mock_resp):
            final_path = downloader.download_file(
                url="https://media.server/video.mp4",
                destination_path=dest,
                expected_sha256=sha256_hash,
            )

        assert os.path.exists(final_path)
        with open(final_path, "rb") as f:
            assert f.read() == test_content


def test_http_downloader_checksum_mismatch():
    test_content = b"Some file content"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(len(test_content))}
    mock_resp.iter_content.return_value = [test_content]

    downloader = HTTPDownloader()

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = os.path.join(tmpdir, "video.mp4")
        with patch.object(downloader.session, "get", return_value=mock_resp):
            with pytest.raises(ValueError, match="Checksum mismatch"):
                downloader.download_file(
                    url="https://media.server/video.mp4",
                    destination_path=dest,
                    expected_sha256="0000000000000000000000000000000000000000000000000000000000000000",
                )


def test_torrent_downloader_export():
    with tempfile.TemporaryDirectory() as tmpdir:
        magnet_uri = "magnet:?xt=urn:btih:3c86b78efa012a402c28712d8be282d813f1a279&dn=Movie"
        target_file = os.path.join(tmpdir, "movie.magnet")
        saved = TorrentDownloader.export_magnet_file(magnet_uri, target_file)
        assert os.path.exists(saved)
        with open(saved, "r") as f:
            assert f.read().strip() == magnet_uri


def test_download_manager_http_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        dl_dir = os.path.join(tmpdir, "downloads")
        storage = StorageManager(db_path=db_path)
        manager = DownloadManager(storage=storage, download_dir=dl_dir)

        stream = StreamSource(
            id="s1",
            provider="Direct",
            title="Sample Stream",
            release_title="Sample.Stream.1080p",
            url="https://example.com/test.mp4",
            quality=Quality.FHD_1080P,
            source_type=SourceType.HTTP,
            size_bytes=100,
        )

        test_data = b"X" * 100
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Length": "100"}
        mock_resp.iter_content.return_value = [test_data]

        with patch.object(manager.http_downloader.session, "get", return_value=mock_resp):
            rec = manager.download_source(stream=stream, media_id="tt001", media_title="Test Movie")

        assert rec.status == DownloadStatus.COMPLETED
        assert os.path.exists(rec.local_path)
        assert rec.source_type == SourceType.HTTP

        # Verify history
        history = manager.list_history()
        assert len(history) == 1
        assert history[0].media_id == "tt001"


def test_download_manager_torrent_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        dl_dir = os.path.join(tmpdir, "downloads")
        storage = StorageManager(db_path=db_path)
        manager = DownloadManager(storage=storage, download_dir=dl_dir)

        stream = StreamSource(
            id="s2",
            provider="Torrentio",
            title="Torrent Stream",
            release_title="Torrent.Stream.2160p",
            info_hash="3c86b78efa012a402c28712d8be282d813f1a279",
            quality=Quality.UHD_4K,
            source_type=SourceType.TORRENT,
        )

        rec = manager.download_source(stream=stream, media_id="tt002", media_title="4K Movie")
        assert rec.source_type == SourceType.TORRENT
        assert rec.local_path.endswith(".magnet")
        assert os.path.exists(rec.local_path)
