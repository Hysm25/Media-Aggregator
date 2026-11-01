"""Regression and audit integration tests verifying edge cases and bug fixes."""

import hashlib
import http.server
import os
import socketserver
import tempfile
import threading
from unittest.mock import MagicMock, patch
import pytest
from media_aggregator.downloader.http import HTTPDownloader
from media_aggregator.downloader.manager import DownloadManager
from media_aggregator.magnet import dispatch_to_torrent_client
from media_aggregator.models import (
    AddonConfig,
    DownloadStatus,
    MediaType,
    Quality,
    SourceType,
    StreamSource,
)
from media_aggregator.parser import parse_torrentio_stream
from media_aggregator.providers.cinemeta import CinemetaProvider
from media_aggregator.providers.generic import GenericStremioProvider
from media_aggregator.providers.registry import ProviderRegistry
from media_aggregator.storage import StorageManager


def test_downloader_cancel_reset_regression():
    """Verify that calling cancel() does not permanently poison subsequent downloads on the instance."""
    dl = HTTPDownloader()
    dl.cancel()
    assert dl._cancel_event.is_set() is True

    test_content = b"Fresh payload after cancellation"
    sha = hashlib.sha256(test_content).hexdigest()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(len(test_content))}
    mock_resp.iter_content.return_value = [test_content]

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = os.path.join(tmpdir, "file.bin")
        with patch.object(dl.session, "get", return_value=mock_resp):
            final_path = dl.download_file("https://example.com/test", dest, expected_sha256=sha)

        assert dl._cancel_event.is_set() is False
        assert os.path.exists(final_path)
        with open(final_path, "rb") as f:
            assert f.read() == test_content


def test_downloader_416_corrupted_part_recovery():
    """Verify that a corrupted .part file causing HTTP 416 is cleaned and redownloaded from 0."""
    correct_data = b"This is the actual complete and valid data payload."
    correct_hash = hashlib.sha256(correct_data).hexdigest()

    class Fail416OnceHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            range_header = self.headers.get("Range")
            if range_header:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(correct_data)}")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Length", str(len(correct_data)))
                self.end_headers()
                self.wfile.write(correct_data)

    with socketserver.TCPServer(("127.0.0.1", 0), Fail416OnceHandler) as httpd:
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = os.path.join(tmpdir, "output.dat")
            part = dest + ".part"
            # Write invalid/corrupt partial file
            with open(part, "wb") as f:
                f.write(b"CORRUPTED WRONG PARTIAL DATA")

            dl = HTTPDownloader()
            final = dl.download_file(
                f"http://127.0.0.1:{port}/file",
                dest,
                expected_sha256=correct_hash,
            )
            assert os.path.exists(final)
            with open(final, "rb") as f:
                assert f.read() == correct_data

        httpd.shutdown()


def test_downloader_416_valid_complete_part():
    """Verify that if .part is already complete and matches expected hash, 416 renames and completes."""
    data = b"Already completed data"
    data_hash = hashlib.sha256(data).hexdigest()

    class Always416Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{len(data)}")
            self.end_headers()

    with socketserver.TCPServer(("127.0.0.1", 0), Always416Handler) as httpd:
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = os.path.join(tmpdir, "output.dat")
            part = dest + ".part"
            with open(part, "wb") as f:
                f.write(data)

            dl = HTTPDownloader()
            final = dl.download_file(
                f"http://127.0.0.1:{port}/file",
                dest,
                expected_sha256=data_hash,
            )
            assert os.path.exists(final)
            with open(final, "rb") as f:
                assert f.read() == data

        httpd.shutdown()


def test_qbittorrent_dispatch():
    """Verify that qbittorrent and qbittorrent-nox are supported in dispatch."""
    magnet = "magnet:?xt=urn:btih:da39a3ee5e6b4b0d3255bfef95601890afd80709"
    with patch("subprocess.Popen") as mock_popen:
        ok, msg = dispatch_to_torrent_client(magnet, client="qbittorrent-nox")
        assert ok is True
        assert "qbittorrent-nox" in msg
        mock_popen.assert_called_once()


def test_parse_torrentio_stream_types():
    """Verify accurate classification of direct HTTP vs Debrid streams in Torrentio parser."""
    # Direct HTTP stream (e.g. from an HTTP archive)
    http_sample = {
        "name": "Archive.org\n1080p",
        "title": "Movie.1080p.mp4\n💾 1.2 GB",
        "url": "https://archive.org/stream/movie.mp4",
    }
    s_http = parse_torrentio_stream(http_sample)
    assert s_http.is_debrid is False
    assert s_http.source_type == SourceType.HTTP

    # Debrid stream with RD+ badge
    debrid_sample = {
        "name": "[RD+] Torrentio\n4k",
        "title": "Movie.2160p.HDR\n💾 15 GB",
        "url": "https://real-debrid.com/d/XYZ/stream.mkv",
    }
    s_debrid = parse_torrentio_stream(debrid_sample)
    assert s_debrid.is_debrid is True
    assert s_debrid.source_type == SourceType.DEBRID


def test_generic_provider_dynamic_search_catalog():
    """Verify GenericStremioProvider extracts custom search catalog id from manifest."""
    provider = GenericStremioProvider(name="Kitsu", base_url="https://anime-kitsu.strem.fun")
    provider._manifest = MagicMock()
    provider._manifest.catalogs = [
        {"id": "kitsu-anime-popular", "type": "anime", "name": "Popular"},
        {"id": "kitsu-anime-list", "type": "anime", "extra": [{"name": "search", "isRequired": True}]},
    ]

    cat_id = provider._find_catalog_id_for_search(MediaType.ANIME)
    assert cat_id == "kitsu-anime-list"


def test_stream_providers_resource_filtering(tmp_path):
    """Verify that get_stream_providers() filters out providers that lack 'stream' resource."""
    storage = StorageManager(db_path=tmp_path / "test.db")
    # Clear and set specific addons
    storage.delete_addon("com.linvo.cinemeta")
    storage.delete_addon("com.stremio.torrentio.addon")
    storage.delete_addon("anime-kitsu")

    # Add stream provider
    storage.save_addon(
        AddonConfig(
            id="stream.addon",
            name="Stream Provider",
            manifest_url="https://example.com/stream/manifest.json",
            base_url="https://example.com/stream",
            config_options={"resources": ["stream"]},
        )
    )
    # Add subtitle-only provider
    storage.save_addon(
        AddonConfig(
            id="sub.addon",
            name="Subtitle Provider",
            manifest_url="https://example.com/sub/manifest.json",
            base_url="https://example.com/sub",
            config_options={"resources": ["subtitles"]},
        )
    )

    registry = ProviderRegistry(storage=storage)
    stream_providers = registry.get_stream_providers()
    assert len(stream_providers) == 1
    assert stream_providers[0].name == "Stream Provider"


def test_download_manager_cancellation_tracking(tmp_path):
    """Verify DownloadManager handles InterruptedError by marking the record CANCELLED."""
    storage = StorageManager(db_path=tmp_path / "test.db")
    manager = DownloadManager(storage=storage, download_dir=tmp_path / "dl")

    stream = StreamSource(
        id="s1",
        provider="HTTP",
        title="Cancelled Stream",
        url="https://example.com/test.mp4",
        source_type=SourceType.HTTP,
    )

    with patch.object(manager.http_downloader, "download_file", side_effect=InterruptedError("Cancelled")):
        with pytest.raises(InterruptedError):
            manager.download_source(stream=stream, media_id="tt001", media_title="Cancelled Movie")

    recs = storage.get_downloads()
    assert len(recs) == 1
    assert recs[0].status == DownloadStatus.CANCELLED
    assert "cancelled by user" in recs[0].error_message.lower()


def test_cinemeta_season_zero_episode_zero():
    """Verify that Season 0 and Episode 0 are not coerced to 1."""
    provider = CinemetaProvider()
    raw_meta = {
        "id": "tt0903747",
        "name": "Breaking Bad",
        "type": "series",
        "videos": [
            {
                "id": "tt0903747:0:0",
                "season": 0,
                "number": 0,
                "name": "Prequel Special",
            }
        ],
    }
    item = provider._parse_meta_dict(raw_meta, MediaType.SERIES)
    assert len(item.episodes) == 1
    ep = item.episodes[0]
    assert ep.season == 0
    assert ep.episode == 0
    assert ep.title == "Prequel Special"
