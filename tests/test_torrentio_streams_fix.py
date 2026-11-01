"""Automated regression tests for Torrentio providers, large stream results, and Telegram stream pagination."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import requests
from aiogram.types import CallbackQuery, Message
from media_aggregator.aggregator import StreamAggregator
from media_aggregator.bot.callbacks import (
    EpisodeCallback,
    MediaCallback,
    NavCallback,
    StreamCallback,
)
from media_aggregator.bot.handlers.media import (
    handle_episode_streams,
    handle_stream_detail_view,
)
from media_aggregator.bot.keyboards import (
    stream_action_keyboard,
    streams_keyboard,
)
from media_aggregator.models import (
    MediaItem,
    MediaType,
    Quality,
    SourceType,
    StreamSource,
    UserRecord,
    UserSettings,
)
from media_aggregator.parser import parse_torrentio_stream
from media_aggregator.providers.torrentio import (
    ALL_TORRENTIO_PROVIDERS,
    DEFAULT_TORRENTIO_PROVIDERS,
    TorrentioProvider,
)
from media_aggregator.services.media_service import MediaService
from media_aggregator.storage import StorageManager


# ============================================================================
# 1. Torrentio Configuration & Provider Auditing Tests
# ============================================================================

def test_torrentio_all_25_providers_configuration():
    """Verify that all 25 official Torrentio scrapers are supported and configurable."""
    assert len(ALL_TORRENTIO_PROVIDERS) == 25
    assert "yts" in ALL_TORRENTIO_PROVIDERS
    assert "thepiratebay" in ALL_TORRENTIO_PROVIDERS
    assert "1337x" in ALL_TORRENTIO_PROVIDERS
    assert "rutor" in ALL_TORRENTIO_PROVIDERS
    assert "rutracker" in ALL_TORRENTIO_PROVIDERS
    assert "torrent9" in ALL_TORRENTIO_PROVIDERS
    assert "besttorrents" in ALL_TORRENTIO_PROVIDERS

    # Test default provider without restricting subset
    provider = TorrentioProvider()
    assert provider.build_config_path() == "sort=qualitysize"

    # Test custom provider subset selection
    custom = TorrentioProvider(providers=["yts", "1337x", "torrentgalaxy"], sort="seeders")
    config_path = custom.build_config_path()
    assert "providers=yts,1337x,torrentgalaxy" in config_path
    assert "sort=seeders" in config_path

    # Test extracting embedded configuration path from base_url
    embedded = TorrentioProvider(base_url="https://torrentio.strem.fun/providers=yts,eztv|sort=size")
    assert embedded.base_url == "https://torrentio.strem.fun"
    assert embedded.custom_config_path == "providers=yts,eztv|sort=size"
    assert embedded.get_effective_base_url() == "https://torrentio.strem.fun/providers=yts,eztv|sort=size"


# ============================================================================
# 2. Large Stream Responses & Pipeline Auditing
# ============================================================================

def test_large_response_with_dozens_or_hundreds_of_streams():
    """Verify responses containing dozens or hundreds of streams are not truncated to 5."""
    raw_streams = []
    for i in range(85):
        raw_streams.append({
            "name": f"Torrentio\n1080p",
            "title": f"Inception.2010.1080p.BluRay.x264.Release.{i}\n👤 {100 - i} 💾 8.{i} GB ⚙️ Tracker{i % 5}",
            "infoHash": f"{i:040x}",
            "fileIdx": 0,
        })

    provider = TorrentioProvider()
    parsed_streams = [parse_torrentio_stream(r) for r in raw_streams]
    assert len(parsed_streams) == 85

    aggregator = StreamAggregator()
    deduped = aggregator.deduplicate_streams(parsed_streams)
    assert len(deduped) == 85

    filtered = aggregator.filter_streams(deduped, min_seeders=1, exclude_cam=True)
    assert len(filtered) == 85

    sorted_streams = aggregator.sort_streams(filtered)
    assert len(sorted_streams) == 85
    # Confirm streams were not artificially truncated to 5
    assert len(sorted_streams) > 5


def test_more_than_five_valid_magnet_results_and_pagination():
    """Verify that stream pagination displays all streams across pages without loss or repetition."""
    streams = [
        StreamSource(
            id=f"stream_{i}",
            provider="Torrentio",
            release_title=f"Movie.Release.{i}.1080p",
            resolution="1080p",
            quality=Quality.FHD_1080P,
            info_hash=f"{i:040x}",
            seeders=50 - i,
            size_display=f"{i + 1} GB",
            size_bytes=(i + 1) * 1024**3,
        )
        for i in range(23)  # 23 streams -> 5 pages of 5 items
    ]

    page_size = 5
    total_pages = math.ceil(len(streams) / page_size)
    assert total_pages == 5

    seen_ids = set()
    for p in range(total_pages):
        kb = streams_keyboard(
            media_id="tt0133093",
            streams=streams,
            season=0,
            episode=0,
            page=p,
            page_size=page_size,
        )
        # Check buttons in keyboard
        inline_rows = kb.inline_keyboard
        # Stream buttons (excluding nav and back rows)
        stream_buttons = [row[0] for row in inline_rows if "StreamCallback" in row[0].callback_data or row[0].callback_data.startswith("st:")]
        expected_count = min(page_size, len(streams) - (p * page_size))
        assert len(stream_buttons) == expected_count

        # Check navigation controls
        if total_pages > 1:
            nav_row = inline_rows[-2]
            nav_texts = [b.text for b in nav_row]
            assert any(f"📄 {p + 1}/{total_pages}" in t for t in nav_texts)
            if p > 0:
                assert any("◀️ Prev" in t for t in nav_texts)
            if p < total_pages - 1:
                assert any("Next ▶️" in t for t in nav_texts)

        for b in stream_buttons:
            # Unpack callback
            cb = StreamCallback.unpack(b.callback_data)
            assert cb.idx not in seen_ids
            seen_ids.add(cb.idx)

    # Every single stream was accessible through pagination
    assert len(seen_ids) == 23


# ============================================================================
# 3. Missing/Invalid Infohashes, Direct Magnets, and Fallbacks
# ============================================================================

def test_stream_pipeline_missing_and_invalid_infohashes():
    """Verify handling of direct magnet URLs, Base32 hashes, and HTTP streams without infohash."""
    # 1. Direct magnet URL in url field
    raw_magnet = {
        "name": "Generic Provider",
        "title": "Film Title\n👤 25 💾 1.2 GB",
        "url": "magnet:?xt=urn:btih:3c86b78efa012a402c28712d8be282d813f1a279&dn=Film",
    }
    s_magnet = parse_torrentio_stream(raw_magnet)
    assert s_magnet.is_torrent is True
    assert s_magnet.info_hash == "3c86b78efa012a402c28712d8be282d813f1a279"

    # 2. Base32 encoded 32-character infohash
    raw_b32 = {
        "name": "Torrentio",
        "title": "Anime Episode\n👤 15 💾 500 MB",
        "infoHash": "HSDLPDX2AEVEALBIOEWYXYUC3AJ7DITZ",  # 32-char Base32 representation
    }
    s_b32 = parse_torrentio_stream(raw_b32)
    assert s_b32.is_torrent is True
    assert len(s_b32.info_hash) == 40  # Successfully converted to hex
    assert s_b32.info_hash == "3c86b78efa012a402c28712d8be282d813f1a279"

    # 3. Pure HTTP stream without infoHash
    raw_http = {
        "name": "HTTP Provider",
        "title": "Direct Web Video",
        "url": "https://stream.server.org/video.mp4",
    }
    s_http = parse_torrentio_stream(raw_http)
    assert s_http.is_torrent is False
    assert s_http.is_http is True
    assert s_http.source_type == SourceType.HTTP
    assert s_http.info_hash is None


# ============================================================================
# 4. Multi-File Torrent Pack Deduplication
# ============================================================================

def test_duplicate_and_distinct_releases_multi_file_packs():
    """Verify that multi-file torrent packs with distinct file_idx are NOT incorrectly merged."""
    aggregator = StreamAggregator()

    # Two episodes from the same complete series torrent pack
    ep1_stream = StreamSource(
        id="pack_ep1",
        provider="Torrentio",
        release_title="Breaking.Bad.COMPLETE.S01-S05.1080p",
        info_hash="aabbccddeeff00112233445566778899aabbccdd",
        file_idx=0,
        seeders=45,
    )
    ep2_stream = StreamSource(
        id="pack_ep2",
        provider="Torrentio",
        release_title="Breaking.Bad.COMPLETE.S01-S05.1080p",
        info_hash="aabbccddeeff00112233445566778899aabbccdd",
        file_idx=1,
        seeders=45,
    )
    # Duplicate of ep1 from another provider
    ep1_dup = StreamSource(
        id="pack_ep1_alt",
        provider="MediaFusion",
        release_title="Breaking.Bad.COMPLETE.S01-S05.1080p",
        info_hash="aabbccddeeff00112233445566778899aabbccdd",
        file_idx=0,
        seeders=50,
    )

    deduped = aggregator.deduplicate_streams([ep1_stream, ep2_stream, ep1_dup])
    # ep1 and ep1_dup should merge, but ep2 (file_idx=1) must be preserved as distinct
    assert len(deduped) == 2
    ep1_merged = next(s for s in deduped if s.file_idx == 0)
    assert ep1_merged.seeders == 50
    assert "Torrentio" in ep1_merged.provider and "MediaFusion" in ep1_merged.provider

    ep2_distinct = next(s for s in deduped if s.file_idx == 1)
    assert ep2_distinct is not None


# ============================================================================
# 5. Mixed HTTP and Torrent Stream Preservation
# ============================================================================

def test_http_streams_versus_magnet_streams_preservation():
    """Verify both HTTP and magnet streams are preserved without discarding either type."""
    aggregator = StreamAggregator()

    torrent_stream = StreamSource(
        id="t1",
        provider="Torrentio",
        release_title="Film.1080p.BluRay",
        info_hash="1122334455667788990011223344556677889900",
        resolution="1080p",
        quality=Quality.FHD_1080P,
        source_type=SourceType.TORRENT,
        seeders=20,
    )
    http_stream = StreamSource(
        id="h1",
        provider="WebDirect",
        release_title="Film.Direct.Stream",
        url="https://archive.org/film.mp4",
        resolution="720p",
        quality=Quality.HD_720P,
        source_type=SourceType.HTTP,
    )

    filtered = aggregator.filter_streams([torrent_stream, http_stream])
    assert len(filtered) == 2
    assert any(s.is_torrent for s in filtered)
    assert any(s.is_http for s in filtered)


# ============================================================================
# 6. Provider Failures & Partial Results Handling
# ============================================================================

def test_provider_failures_and_partial_results():
    """Verify aggregator gracefully handles provider errors while preserving successful results."""
    aggregator = StreamAggregator()

    working_provider = MagicMock()
    working_provider.get_streams.return_value = [
        StreamSource(id="w1", provider="Working", info_hash="1111111111111111111111111111111111111111", seeders=10)
    ]

    failing_provider = MagicMock()
    failing_provider.get_streams.side_effect = requests.exceptions.ConnectTimeout("Add-on timed out")

    results = aggregator.aggregate_streams(
        media_type=MediaType.MOVIE,
        media_id="tt0133093",
        providers=[working_provider, failing_provider],
        record_history=False,
    )
    assert len(results) == 1
    assert results[0].id == "w1"


# ============================================================================
# 7. End-to-End Telegram Stream Browsing & Pagination Flow
# ============================================================================

@pytest.mark.asyncio
async def test_telegram_ui_stream_pagination_flow(tmp_path):
    """Simulate complete Telegram stream browsing: page 0 -> page 1 -> view stream -> back to page 1."""
    storage = StorageManager(db_path=tmp_path / "test_stream_ui.db")
    cinemeta_mock = MagicMock()
    media_item = MediaItem(id="tt1375666", title="Inception", type=MediaType.MOVIE)
    cinemeta_mock.get_metadata.return_value = media_item

    # 12 streams -> 3 pages of 5 items
    mock_streams = [
        StreamSource(
            id=f"stream_{i}",
            provider="Torrentio",
            release_title=f"Inception.2010.Release.{i}.1080p",
            resolution="1080p",
            quality=Quality.FHD_1080P,
            info_hash=f"{i:040x}",
            seeders=50 - i,
            size_display=f"{i + 1} GB",
            size_bytes=(i + 1) * 1024**3,
        )
        for i in range(12)
    ]

    media_service = MediaService(storage=storage, cinemeta=cinemeta_mock)
    user = UserRecord(user_id=777, username="stream_tester", settings=UserSettings())

    with patch.object(media_service, "get_streams", return_value=mock_streams):
        # Step A: User opens movie streams (Page 0)
        cb_page0 = AsyncMock()
        cb_page0.message = AsyncMock()
        await handle_episode_streams(
            cb_page0,
            EpisodeCallback(id="tt1375666", season=0, episode=0, page=0),
            media_service,
            user,
        )
        assert cb_page0.message.edit_text.called
        text_page0 = cb_page0.message.edit_text.call_args[0][0]
        assert "Found **12** stream sources" in text_page0
        assert "Page **1/3**" in text_page0
        assert "Inception.2010.Release.0" in text_page0
        kb_page0 = cb_page0.message.edit_text.call_args[1]["reply_markup"]
        assert any("Next ▶️" in b.text for row in kb_page0.inline_keyboard for b in row)

        # Step B: User navigates to Page 1
        cb_page1 = AsyncMock()
        cb_page1.message = AsyncMock()
        await handle_episode_streams(
            cb_page1,
            EpisodeCallback(id="tt1375666", season=0, episode=0, page=1),
            media_service,
            user,
        )
        assert cb_page1.message.edit_text.called
        text_page1 = cb_page1.message.edit_text.call_args[0][0]
        assert "Page **2/3**" in text_page1
        assert "Inception.2010.Release.5" in text_page1
        kb_page1 = cb_page1.message.edit_text.call_args[1]["reply_markup"]
        assert any("◀️ Prev" in b.text for row in kb_page1.inline_keyboard for b in row)
        assert any("Next ▶️" in b.text for row in kb_page1.inline_keyboard for b in row)

        # Step C: User views details for stream index 7 (located on page 1)
        cb_view = AsyncMock()
        cb_view.message = AsyncMock()
        await handle_stream_detail_view(
            cb_view,
            StreamCallback(id="tt1375666", season=0, episode=0, idx=7, action="view", page=1),
            media_service,
            user,
        )
        assert cb_view.message.edit_text.called
        detail_text = cb_view.message.edit_text.call_args[0][0]
        assert "Stream Source Information" in detail_text
        assert "BitTorrent (Magnet Available)" in detail_text
        assert "Inception.2010.Release.7" in detail_text

        # Verify Back button returns user to Page 1
        detail_kb = cb_view.message.edit_text.call_args[1]["reply_markup"]
        back_btn = next(b for row in detail_kb.inline_keyboard for b in row if "Back to Streams" in b.text)
        back_cb = EpisodeCallback.unpack(back_btn.callback_data)
        assert back_cb.page == 1


# ============================================================================
# 8. Live Torrentio Endpoint Verification
# ============================================================================

def test_live_torrentio_api_vs_displayed_count():
    """Verify against live Torrentio endpoint that >5 results are retrieved and paginated."""
    try:
        r = requests.get(
            "https://torrentio.strem.fun/manifest.json",
            headers={"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0 Stremio/4.4.168"},
            timeout=4,
        )
        if r.status_code != 200:
            pytest.skip("Torrentio endpoint unreachable")
    except Exception:
        pytest.skip("No external network access available")

    provider = TorrentioProvider()
    live_streams = provider.get_streams(media_type=MediaType.SERIES, media_id="tt0903747", season=1, episode=1)
    
    # 1. API result count
    assert len(live_streams) > 5, f"Expected >5 streams from live Torrentio, got {len(live_streams)}"
    
    # 2. Filtering & Deduplication retention
    aggregator = StreamAggregator()
    deduped = aggregator.deduplicate_streams(live_streams)
    filtered = aggregator.filter_streams(deduped, min_seeders=1, exclude_cam=True)
    assert len(filtered) > 5
    
    # 3. Accessibility through pagination
    page_size = 5
    total_pages = math.ceil(len(filtered) / page_size)
    assert total_pages > 1

    # Check page 0 and page 1 have distinct, non-empty stream items
    page_0_kb = streams_keyboard("tt0903747", filtered, season=1, episode=1, page=0, page_size=page_size)
    page_1_kb = streams_keyboard("tt0903747", filtered, season=1, episode=1, page=1, page_size=page_size)

    page_0_cbs = [StreamCallback.unpack(r[0].callback_data).idx for r in page_0_kb.inline_keyboard if r[0].callback_data.startswith("st:")]
    page_1_cbs = [StreamCallback.unpack(r[0].callback_data).idx for r in page_1_kb.inline_keyboard if r[0].callback_data.startswith("st:")]

    assert len(page_0_cbs) == 5
    assert len(page_1_cbs) == 5
    assert set(page_0_cbs).isdisjoint(set(page_1_cbs))
