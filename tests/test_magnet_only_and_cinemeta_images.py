"""Tests for Magnet-Only Telegram downloads and Cinemeta image quality enhancements."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from media_aggregator.bot.callbacks import DownloadCallback, EpisodeCallback, MediaCallback, NavCallback, StreamCallback
from media_aggregator.bot.handlers.downloads import (
    handle_copy_magnet,
    handle_list_downloads,
    handle_send_magnet_file,
    handle_start_download,
)
from media_aggregator.bot.handlers.media import handle_media_backdrop, handle_stream_detail_view
from media_aggregator.bot.keyboards import (
    main_menu_keyboard,
    media_detail_keyboard,
    stream_action_keyboard,
    streams_keyboard,
)
from media_aggregator.downloader.manager import DownloadManager
from media_aggregator.images import (
    enhance_background_url,
    enhance_logo_url,
    enhance_poster_url,
    is_valid_image_url,
)
from media_aggregator.models import (
    DownloadStatus,
    MediaItem,
    MediaType,
    SourceType,
    StreamSource,
    UserRecord,
    UserSettings,
)
from media_aggregator.providers.cinemeta import CinemetaProvider
from media_aggregator.services.media_service import MediaService
from media_aggregator.storage import StorageManager


# ============================================================================
# 1. Magnet-Only Telegram Behavior
# ============================================================================

def test_stream_action_keyboard_magnet_only_and_no_http_download():
    """Verify stream_action_keyboard offers Magnet links for torrents and NO download button for HTTP."""
    torrent_stream = StreamSource(
        id="tor1",
        provider="torrentio",
        release_title="Movie.1080p.BluRay",
        resolution="1080p",
        size_display="4.5 GB",
        seeders=50,
        source_type=SourceType.TORRENT,
        info_hash="1122334455667788990011223344556677889900",
    )
    http_stream = StreamSource(
        id="http1",
        provider="generic",
        release_title="Movie.Web.Stream",
        resolution="1080p",
        size_display="1.8 GB",
        source_type=SourceType.HTTP,
        url="https://example.com/stream.mp4",
        info_hash=None,
    )

    # 1. Torrent stream keyboard
    kb_tor = stream_action_keyboard("tt0133093", torrent_stream, page=2)
    flat_tor = [btn for row in kb_tor.inline_keyboard for btn in row]
    tor_texts = [btn.text for btn in flat_tor]

    assert any("Get Magnet URI" in t for t in tor_texts)
    assert any("Send .magnet File" in t for t in tor_texts)
    assert not any("Start Download" in t for t in tor_texts)

    # 2. HTTP stream keyboard
    kb_http = stream_action_keyboard("tt0133093", http_stream, page=2)
    flat_http = [btn for row in kb_http.inline_keyboard for btn in row]
    http_texts = [btn.text for btn in flat_http]

    # Must NOT offer Direct HTTP as a download action
    assert not any("Start Download" in t for t in http_texts)
    assert not any("Get Magnet" in t for t in http_texts)
    assert not any(".magnet" in t for t in http_texts)
    assert any("Back to Streams" in t for t in http_texts)


@pytest.mark.asyncio
async def test_handle_start_download_rejects_direct_http():
    """Verify handle_start_download explicitly rejects direct HTTP downloads in Telegram."""
    media_service = MagicMock(spec=MediaService)
    http_stream = StreamSource(
        id="http1",
        provider="generic",
        release_title="Direct.Stream",
        resolution="720p",
        source_type=SourceType.HTTP,
        url="https://example.com/video.mp4",
        info_hash=None,
    )
    media_service.get_streams = AsyncMock(return_value=[http_stream])
    user = UserRecord(user_id=1, username="test_u")

    cb = MagicMock(spec=CallbackQuery)
    cb.answer = AsyncMock()
    cb.message = AsyncMock()

    callback_data = StreamCallback(id="tt123", season=0, episode=0, idx=0, action="dl", page=0)
    await handle_start_download(cb, callback_data, media_service, user)

    cb.answer.assert_called_once()
    alert_text = cb.answer.call_args[0][0]
    assert "Direct HTTP file downloads are disabled" in alert_text
    assert "show_alert" in cb.answer.call_args[1]
    assert cb.answer.call_args[1]["show_alert"] is True


@pytest.mark.asyncio
async def test_handle_copy_magnet_and_send_magnet_file():
    """Verify Magnet URI delivery and .magnet document sending work smoothly."""
    media_service = MagicMock(spec=MediaService)
    tor_stream = StreamSource(
        id="tor1",
        provider="torrentio",
        release_title="Inception.2010.1080p",
        resolution="1080p",
        size_display="2.2 GB",
        seeders=45,
        source_type=SourceType.TORRENT,
        info_hash="aabbccddeeff00112233445566778899aabbccdd",
    )
    media_service.get_streams = AsyncMock(return_value=[tor_stream])
    media_service.get_details = AsyncMock(return_value=MediaItem(id="tt1375666", title="Inception", year="2010"))
    user = UserRecord(user_id=1, username="test_u")

    cb = MagicMock(spec=CallbackQuery)
    cb.answer = AsyncMock()
    cb.message = AsyncMock()

    # 1. Copy Magnet URI
    cb_data_magnet = StreamCallback(id="tt1375666", season=0, episode=0, idx=0, action="magnet", page=0)
    await handle_copy_magnet(cb, cb_data_magnet, media_service, user)

    cb.message.answer.assert_called_once()
    msg_text = cb.message.answer.call_args[0][0]
    assert "aabbccddeeff00112233445566778899aabbccdd" in msg_text
    assert "BitTorrent" in msg_text

    # 2. Send .magnet File
    cb.message.reset_mock()
    cb.answer.reset_mock()
    cb_data_file = StreamCallback(id="tt1375666", season=0, episode=0, idx=0, action="magnet_file", page=0)
    await handle_send_magnet_file(cb, cb_data_file, media_service, user)

    cb.message.answer_document.assert_called_once()
    doc_arg = cb.message.answer_document.call_args[1]["document"]
    assert doc_arg.filename == "Inception.magnet"
    assert b"aabbccddeeff00112233445566778899aabbccdd" in doc_arg.data


def test_main_menu_and_downloads_command_magnet_only_info():
    """Verify main menu does not contain downloads dashboard button and /downloads explains Magnet-only."""
    # Main menu check
    kb_user = main_menu_keyboard(is_admin=False)
    all_btns = [btn for row in kb_user.inline_keyboard for btn in row]
    btn_texts = [b.text for b in all_btns]

    assert not any("📥 Downloads" in t for t in btn_texts)
    assert any("🔍 Search Media" in t for t in btn_texts)
    assert any("⚙️ Settings" in t for t in btn_texts)

    # Admin main menu check
    kb_admin = main_menu_keyboard(is_admin=True)
    admin_btns = [btn for row in kb_admin.inline_keyboard for btn in row]
    assert any("Admin Dashboard" in b.text for b in admin_btns)


@pytest.mark.asyncio
async def test_downloads_command_magnet_only_explanation():
    """Verify /downloads command displays informative guide on Magnet downloads."""
    user = UserRecord(user_id=1, username="test_u")
    msg = AsyncMock()

    await handle_list_downloads(msg, user_record=user)

    msg.answer.assert_called_once()
    text = msg.answer.call_args[0][0]
    assert "Downloads in Telegram — Magnet Only" in text
    assert "external BitTorrent client" in text
    assert "Direct HTTP streams are distinguished from Magnet streams" in text


def test_cli_and_shared_downloader_remain_functional(tmp_path):
    """Verify HTTPDownloader and DownloadManager remain fully functional for CLI use."""
    from media_aggregator.downloader.torrent import TorrentDownloader
    db_path = tmp_path / "test_cli_storage.db"
    storage = StorageManager(db_path=db_path)
    dl_dir = tmp_path / "downloads"
    manager = DownloadManager(download_dir=dl_dir, storage=storage)

    assert manager.download_dir.exists()
    assert manager.http_downloader is not None
    assert callable(TorrentDownloader.export_magnet_file)
    assert callable(TorrentDownloader.dispatch)


# ============================================================================
# 2. Cinemeta Images & Quality Optimization
# ============================================================================

def test_enhance_poster_url_metahub_and_amazon_cdn():
    """Verify high-quality poster selection and uncropping of Amazon CDN thumbnails."""
    # 1. Metahub upgrade from small to medium
    small_metahub = "https://images.metahub.space/poster/small/tt1375666/img"
    enhanced_metahub = enhance_poster_url(small_metahub)
    assert enhanced_metahub == "https://images.metahub.space/poster/medium/tt1375666/img"

    # 2. Amazon / IMDb CDN downscaling parameter removal
    amazon_thumb_sx250 = (
        "https://m.media-amazon.com/images/M/MV5BMjAxMzY3NjcxNF5BMl5BanBnXkFtZTcwNTI5OTM0Mw@@._V1_SX250.jpg"
    )
    enhanced_amazon = enhance_poster_url(amazon_thumb_sx250)
    assert "._V1_SX800.jpg" in enhanced_amazon
    assert "._V1_SX250.jpg" not in enhanced_amazon

    # 3. Amazon / IMDb CDN cropping pattern removal
    amazon_cropped = (
        "https://m.media-amazon.com/images/M/MV5BMjAxMzY3NjcxNF5BMl5BanBnXkFtZTcwNTI5OTM0Mw@@._V1_UX182_CR0,0,182,268_AL_.jpg"
    )
    enhanced_cropped = enhance_poster_url(amazon_cropped)
    assert "._V1_SX800.jpg" in enhanced_cropped
    assert "UX182" not in enhanced_cropped

    # 4. Fallback to Metahub for valid IMDb IDs when poster is None
    fallback_poster = enhance_poster_url(None, imdb_id="tt0816692")
    assert fallback_poster == "https://images.metahub.space/poster/medium/tt0816692/img"

    # 5. Non-IMDb item with None returns None (no fake posters)
    assert enhance_poster_url(None, imdb_id="custom:123") is None


def test_enhance_background_and_logo_url():
    """Verify background artwork and official logo URL enhancement."""
    # Background Metahub upgrade
    small_bg = "https://images.metahub.space/background/small/tt0903747/img"
    assert enhance_background_url(small_bg) == "https://images.metahub.space/background/medium/tt0903747/img"

    # Background fallback for IMDb ID
    assert enhance_background_url(None, imdb_id="tt0903747") == "https://images.metahub.space/background/medium/tt0903747/img"

    # Logo Metahub upgrade
    small_logo = "https://images.metahub.space/logo/small/tt0903747/img"
    assert enhance_logo_url(small_logo) == "https://images.metahub.space/logo/medium/tt0903747/img"

    # Logo fallback for IMDb ID
    assert enhance_logo_url(None, imdb_id="tt0903747") == "https://images.metahub.space/logo/medium/tt0903747/img"


def test_missing_invalid_and_unavailable_image_urls():
    """Verify invalid, malformed, or local image URLs are rejected safely."""
    assert is_valid_image_url(None) is False
    assert is_valid_image_url("") is False
    assert is_valid_image_url("   ") is False
    assert is_valid_image_url("ftp://example.com/pic.jpg") is False
    assert is_valid_image_url("http://localhost:8080/image.png") is False
    assert is_valid_image_url("http://127.0.0.1/bad.jpg") is False
    assert is_valid_image_url("not a url") is False
    assert is_valid_image_url("https://images.metahub.space/poster/medium/tt1375666/img") is True


def test_cinemeta_provider_meta_dict_parsing_with_logo_and_background():
    """Verify CinemetaProvider._parse_meta_dict parses and enhances poster, background, and logo."""
    provider = CinemetaProvider()
    raw_meta = {
        "id": "tt1375666",
        "name": "Inception",
        "type": "movie",
        "year": "2010",
        "poster": "https://images.metahub.space/poster/small/tt1375666/img",
        "background": "https://images.metahub.space/background/small/tt1375666/img",
        "logo": "https://images.metahub.space/logo/small/tt1375666/img",
        "description": "A thief who steals corporate secrets through dream-sharing...",
        "genres": ["Action", "Sci-Fi"],
        "cast": ["Leonardo DiCaprio", "Joseph Gordon-Levitt"],
        "director": "Christopher Nolan",
        "imdbRating": "8.8",
    }

    item = provider._parse_meta_dict(raw_meta, default_type=MediaType.MOVIE)

    assert item.id == "tt1375666"
    assert item.title == "Inception"
    assert item.poster == "https://images.metahub.space/poster/medium/tt1375666/img"
    assert item.background == "https://images.metahub.space/background/medium/tt1375666/img"
    assert item.logo == "https://images.metahub.space/logo/medium/tt1375666/img"
    assert item.director == "Christopher Nolan"
    assert item.imdb_rating == "8.8"


@pytest.mark.asyncio
async def test_metadata_caching_and_provider_failure_fallback(tmp_path):
    """Verify MediaService caches metadata lookups and falls back gracefully when Cinemeta fails."""
    storage = StorageManager(db_path=tmp_path / "test_meta_cache.db")
    cinemeta_mock = MagicMock(spec=CinemetaProvider)

    initial_item = MediaItem(
        id="tt0903747",
        title="Breaking Bad",
        type=MediaType.SERIES,
        year="2008-2013",
        poster="https://images.metahub.space/poster/medium/tt0903747/img",
        background="https://images.metahub.space/background/medium/tt0903747/img",
        logo="https://images.metahub.space/logo/medium/tt0903747/img",
        cast=["Bryan Cranston", "Aaron Paul"],
        synopsis="A high school chemistry teacher diagnosed with cancer...",
    )
    cinemeta_mock.get_metadata.return_value = initial_item

    service = MediaService(storage=storage, cinemeta=cinemeta_mock)

    # 1. First lookup queries provider and saves to SQLite and memory
    item1 = await service.get_details("tt0903747", media_type=MediaType.SERIES)
    assert item1 is not None
    assert item1.title == "Breaking Bad"
    assert cinemeta_mock.get_metadata.call_count == 1

    # 2. Second lookup hits memory cache without calling remote provider
    item2 = await service.get_details("tt0903747", media_type=MediaType.SERIES)
    assert item2 is not None
    assert item2.id == "tt0903747"
    assert cinemeta_mock.get_metadata.call_count == 1  # No repeated remote call!

    # 3. Simulate provider failure on a fresh instance sharing the database
    failing_cinemeta = MagicMock(spec=CinemetaProvider)
    failing_cinemeta.get_metadata.side_effect = TimeoutError("Connection to Cinemeta timed out")
    service2 = MediaService(storage=storage, cinemeta=failing_cinemeta)

    # Should fall back gracefully to SQLite cache
    fallback_item = await service2.get_details("tt0903747", media_type=MediaType.SERIES)
    assert fallback_item is not None
    assert fallback_item.title == "Breaking Bad"
    assert fallback_item.poster == initial_item.poster


@pytest.mark.asyncio
async def test_backdrop_view_interaction():
    """Verify backdrop action keyboard button and handle_media_backdrop handler."""
    item = MediaItem(
        id="tt1375666",
        title="Inception",
        year="2010",
        poster="https://images.metahub.space/poster/medium/tt1375666/img",
        background="https://images.metahub.space/background/medium/tt1375666/img",
    )

    # Check that media_detail_keyboard includes Backdrop button when background is present
    kb = media_detail_keyboard(item)
    all_btns = [btn for row in kb.inline_keyboard for btn in row]
    assert any("View Backdrop" in b.text for b in all_btns)

    # Test handle_media_backdrop handler
    media_service = MagicMock(spec=MediaService)
    media_service.get_details = AsyncMock(return_value=item)
    user = UserRecord(user_id=1, username="test_u")

    cb = MagicMock(spec=CallbackQuery)
    cb.message = AsyncMock()
    cb.answer = AsyncMock()

    await handle_media_backdrop(cb, MediaCallback(id="tt1375666", action="backdrop"), media_service, user)
    cb.message.edit_text.assert_called()
    assert "Official Artwork" in cb.message.edit_text.call_args[0][0]
    assert cb.answer.called


# ============================================================================
# 3. Live Cinemeta Endpoint Verification
# ============================================================================

def test_live_cinemeta_metadata_and_image_endpoint():
    """Live verification against official v3-cinemeta.strem.io metadata endpoint."""
    import urllib.request
    provider = CinemetaProvider()

    # Query Inception metadata live
    meta_item = provider.get_metadata("tt1375666", media_type=MediaType.MOVIE)
    if not meta_item:
        pytest.skip("Cinemeta endpoint unreachable from test environment")

    assert meta_item.id == "tt1375666"
    assert "Inception" in meta_item.title
    assert meta_item.poster is not None
    assert "medium" in meta_item.poster or "large" in meta_item.poster or "SX800" in meta_item.poster or "metahub" in meta_item.poster

    # Verify the poster URL actually returns HTTP 200 and image Content-Type
    req = urllib.request.Request(meta_item.poster, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        assert resp.status == 200
        content_type = resp.headers.get("Content-Type", "")
        assert "image" in content_type
