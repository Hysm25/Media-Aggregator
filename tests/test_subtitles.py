"""Comprehensive tests for subtitle parsing, models, Telegram UI, and delivery workflows."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from media_aggregator.bot.callbacks import StreamCallback, SubtitleCallback
from media_aggregator.bot.handlers.media import handle_subtitle_get, handle_subtitles_list
from media_aggregator.bot.keyboards import stream_action_keyboard, subtitles_list_keyboard
from media_aggregator.models import (
    MediaItem,
    MediaType,
    SourceType,
    StreamSource,
    SubtitleTrack,
    UserRecord,
    UserSettings,
)
from media_aggregator.parser import (
    normalize_language_code,
    parse_generic_stream,
    parse_subtitles,
    parse_torrentio_stream,
)
from media_aggregator.services.media_service import MediaService
from media_aggregator.storage import StorageManager


# ============================================================================
# 1. Language Normalization & Parsing
# ============================================================================

def test_normalize_language_code():
    """Verify ISO 639 codes are normalized to human-readable language names."""
    assert normalize_language_code("eng") == "English"
    assert normalize_language_code("en") == "English"
    assert normalize_language_code("spa") == "Spanish"
    assert normalize_language_code("es") == "Spanish"
    assert normalize_language_code("fre") == "French"
    assert normalize_language_code("fra") == "French"
    assert normalize_language_code("fr") == "French"
    assert normalize_language_code("ger") == "German"
    assert normalize_language_code("deu") == "German"
    assert normalize_language_code("ita") == "Italian"
    assert normalize_language_code("por") == "Portuguese"
    assert normalize_language_code("rus") == "Russian"
    assert normalize_language_code("jpn") == "Japanese"
    assert normalize_language_code("ara") == "Arabic"
    assert normalize_language_code("chi") == "Chinese"
    assert normalize_language_code("zho") == "Chinese"
    assert normalize_language_code("kor") == "Korean"
    assert normalize_language_code("tur") == "Turkish"
    # Unknown or custom codes
    assert normalize_language_code("xyz") == "Xyz"
    assert normalize_language_code("") == "Unknown"


def test_parse_subtitles_valid_and_invalid():
    """Verify parsing raw subtitle dictionaries into SubtitleTrack instances."""
    raw = [
        {"id": "sub_en", "url": "https://example.com/subs/en.vtt", "lang": "eng"},
        {"id": "sub_es", "url": "https://example.com/subs/es.srt", "lang": "spa", "label": "SDH"},
        {"id": "sub_no_url", "url": "", "lang": "fra"},
        {"id": "sub_ftp", "url": "ftp://example.com/sub.srt", "lang": "fra"},
        "invalid_item",
        {"id": "sub_no_lang", "url": "https://example.com/subs/unknown.vtt"},
    ]

    tracks = parse_subtitles(raw)
    assert len(tracks) == 3

    assert tracks[0].id == "sub_en"
    assert tracks[0].url == "https://example.com/subs/en.vtt"
    assert tracks[0].lang == "eng"
    assert tracks[0].format == "vtt"
    assert tracks[0].display_name == "English [.vtt]"

    assert tracks[1].id == "sub_es"
    assert tracks[1].url == "https://example.com/subs/es.srt"
    assert tracks[1].lang == "spa"
    assert tracks[1].format == "srt"
    assert tracks[1].label == "SDH"
    assert tracks[1].display_name == "Spanish (SDH) [.srt]"

    assert tracks[2].id == "sub_no_lang"
    assert tracks[2].lang == "und"
    assert tracks[2].format == "vtt"


def test_parse_subtitles_non_list():
    """Verify parse_subtitles handles None or non-list inputs gracefully."""
    assert parse_subtitles(None) == []
    assert parse_subtitles({}) == []
    assert parse_subtitles("subtitles") == []


def test_stream_parsers_extract_subtitles():
    """Verify that both parse_generic_stream and parse_torrentio_stream parse subtitle arrays."""
    generic_raw = {
        "title": "Big Buck Bunny 1080p",
        "url": "https://example.com/video.mp4",
        "subtitles": [
            {"id": "1", "url": "https://example.com/en.srt", "lang": "eng"},
            {"id": "2", "url": "https://example.com/fr.vtt", "lang": "fre"},
        ],
    }
    s_gen = parse_generic_stream(generic_raw, provider_name="TestProvider")
    assert len(s_gen.subtitles) == 2
    assert s_gen.subtitles[0].format == "srt"
    assert s_gen.subtitles[1].format == "vtt"
    assert s_gen.subtitles[0].display_name == "English [.srt]"
    assert s_gen.subtitles[1].display_name == "French [.vtt]"

    # Torrentio stream with subtitles (if provided)
    tor_raw = {
        "name": "Torrentio\n1080p",
        "title": "Inception 2010 1080p Bluray\n👤 50 💾 2.5 GB ⚙️ YTS",
        "infoHash": "1122334455667788990011223344556677889900",
        "subtitles": [
            {"id": "1", "url": "https://example.com/incept_en.vtt", "lang": "eng"},
        ],
    }
    s_tor = parse_torrentio_stream(tor_raw, provider_name="Torrentio")
    assert len(s_tor.subtitles) == 1
    assert s_tor.subtitles[0].lang == "eng"
    assert s_tor.subtitles[0].format == "vtt"

    # Torrentio standard response (0 subtitles)
    tor_standard = {
        "name": "Torrentio\n1080p",
        "title": "Inception 2010 1080p Bluray\n👤 50 💾 2.5 GB ⚙️ YTS",
        "infoHash": "1122334455667788990011223344556677889900",
    }
    s_tor_empty = parse_torrentio_stream(tor_standard, provider_name="Torrentio")
    assert len(s_tor_empty.subtitles) == 0


# ============================================================================
# 2. Telegram Keyboards & Subtitle Buttons
# ============================================================================

def test_stream_action_keyboard_subtitle_button():
    """Verify stream_action_keyboard conditionally displays '💬 Subtitles' only when subtitles exist."""
    sub_track = SubtitleTrack(id="1", url="https://example.com/en.srt", lang="eng", format="srt")

    stream_with_subs = StreamSource(
        id="s1",
        provider="test",
        release_title="Movie.1080p",
        subtitles=[sub_track],
        source_type=SourceType.HTTP,
        url="https://example.com/stream.mp4",
    )
    stream_without_subs = StreamSource(
        id="s2",
        provider="test",
        release_title="Movie.1080p",
        subtitles=[],
        source_type=SourceType.HTTP,
        url="https://example.com/stream.mp4",
    )

    kb_subs = stream_action_keyboard("tt1375666", stream_with_subs)
    buttons_subs = [b.text for row in kb_subs.inline_keyboard for b in row]
    assert any("💬 Subtitles (1)" in b for b in buttons_subs)

    kb_no_subs = stream_action_keyboard("tt1375666", stream_without_subs)
    buttons_no_subs = [b.text for row in kb_no_subs.inline_keyboard for b in row]
    assert not any("Subtitles" in b for b in buttons_no_subs)


def test_subtitles_list_keyboard_layout():
    """Verify subtitles_list_keyboard creates rows for each track and a back button."""
    subs = [
        SubtitleTrack(id="1", url="https://example.com/en.vtt", lang="eng", format="vtt"),
        SubtitleTrack(id="2", url="https://example.com/es.srt", lang="spa", format="srt"),
    ]
    kb = subtitles_list_keyboard("tt1375666", subs, season=1, episode=2, stream_idx=3, page=1)
    flat = [b for row in kb.inline_keyboard for b in row]
    texts = [b.text for b in flat]

    assert any("1. English [.vtt]" in t for t in texts)
    assert any("2. Spanish [.srt]" in t for t in texts)
    assert any("🔙 Back to Stream" in t for t in texts)
    assert any("🏠 Home" in t for t in texts)


# ============================================================================
# 3. Subtitle Handlers & Delivery Workflows
# ============================================================================

@pytest.mark.asyncio
async def test_handle_subtitles_list_success():
    """Verify handle_subtitles_list renders the subtitle menu when tracks exist."""
    callback = MagicMock(spec=CallbackQuery)
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()

    callback_data = SubtitleCallback(id="tt1375666", stream_idx=0, action="list")
    user_record = UserRecord(user_id=123, is_admin=True)

    stream = StreamSource(
        id="s1",
        provider="test",
        release_title="Inception.1080p",
        subtitles=[
            SubtitleTrack(id="1", url="https://example.com/en.vtt", lang="eng", format="vtt"),
            SubtitleTrack(id="2", url="https://example.com/es.srt", lang="spa", format="srt"),
        ],
    )

    media_service = MagicMock(spec=MediaService)
    media_service.get_streams = AsyncMock(return_value=[stream])

    await handle_subtitles_list(callback, callback_data, media_service, user_record)

    callback.message.edit_text.assert_called_once()
    call_args = callback.message.edit_text.call_args[0][0]
    assert "External Subtitle Tracks" in call_args
    assert "Inception.1080p" in call_args
    callback.answer.assert_called_once()


@pytest.mark.asyncio
async def test_handle_subtitles_list_empty():
    """Verify handle_subtitles_list alerts the user if no subtitles exist."""
    callback = MagicMock(spec=CallbackQuery)
    callback.answer = AsyncMock()

    callback_data = SubtitleCallback(id="tt1375666", stream_idx=0, action="list")
    user_record = UserRecord(user_id=123, is_admin=True)

    stream = StreamSource(id="s1", provider="test", subtitles=[])
    media_service = MagicMock(spec=MediaService)
    media_service.get_streams = AsyncMock(return_value=[stream])

    await handle_subtitles_list(callback, callback_data, media_service, user_record)

    callback.answer.assert_called_once_with(
        "No external subtitle tracks available for this stream.",
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_handle_subtitle_get_successful_download():
    """Verify handle_subtitle_get downloads the subtitle and delivers it as a Telegram document."""
    callback = MagicMock(spec=CallbackQuery)
    callback.message = MagicMock(spec=Message)
    callback.message.answer_document = AsyncMock()
    callback.answer = AsyncMock()

    callback_data = SubtitleCallback(id="tt1375666", stream_idx=0, sub_idx=0, action="get")
    user_record = UserRecord(user_id=123, is_admin=True)

    sub = SubtitleTrack(id="1", url="https://example.com/sub.srt", lang="eng", format="srt")
    stream = StreamSource(id="s1", provider="test", subtitles=[sub])

    media_item = MediaItem(id="tt1375666", title="Inception", type=MediaType.MOVIE)
    media_service = MagicMock(spec=MediaService)
    media_service.get_streams = AsyncMock(return_value=[stream])
    media_service.get_details = AsyncMock(return_value=media_item)

    mock_content = b"1\n00:00:01,000 --> 00:00:04,000\nHello World\n"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_content
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        await handle_subtitle_get(callback, callback_data, media_service, user_record)

    callback.message.answer_document.assert_called_once()
    doc_arg = callback.message.answer_document.call_args[1]["document"]
    caption_arg = callback.message.answer_document.call_args[1]["caption"]

    assert doc_arg.filename == "Inception_eng.srt"
    assert "Inception_eng.srt" in caption_arg
    assert "English [.srt]" in caption_arg
    assert "VLC / MX Player" in caption_arg
    assert "https://example.com/sub.srt" in caption_arg
    callback.answer.assert_called_once_with("💬 English [.srt] sent!")


@pytest.mark.asyncio
async def test_handle_subtitle_get_broken_remote_url():
    """Verify handle_subtitle_get falls back gracefully when the remote subtitle URL is unreachable."""
    callback = MagicMock(spec=CallbackQuery)
    callback.message = MagicMock(spec=Message)
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()

    callback_data = SubtitleCallback(id="tt1375666", stream_idx=0, sub_idx=0, action="get")
    user_record = UserRecord(user_id=123, is_admin=True)

    sub = SubtitleTrack(id="1", url="https://broken.invalid/sub.vtt", lang="eng", format="vtt")
    stream = StreamSource(id="s1", provider="test", subtitles=[sub])

    media_item = MediaItem(id="tt1375666", title="Inception", type=MediaType.MOVIE)
    media_service = MagicMock(spec=MediaService)
    media_service.get_streams = AsyncMock(return_value=[stream])
    media_service.get_details = AsyncMock(return_value=media_item)

    with patch("urllib.request.urlopen", side_effect=Exception("HTTP 404 Not Found")):
        await handle_subtitle_get(callback, callback_data, media_service, user_record)

    callback.message.answer.assert_called_once()
    text_arg = callback.message.answer.call_args[1]["text"]
    assert "https://broken.invalid/sub.vtt" in text_arg
    assert "Remote subtitle server returned an error" in text_arg
    callback.answer.assert_called_once_with("Subtitle link delivered!", show_alert=True)


# ============================================================================
# 4. Magnet-Only Download Invariant Verification
# ============================================================================

def test_magnet_only_invariant_preserved():
    """Confirm that subtitle integration did not reintroduce direct HTTP downloads in Telegram."""
    torrent_stream = StreamSource(
        id="tor1",
        provider="torrentio",
        release_title="Inception.1080p",
        info_hash="1122334455667788990011223344556677889900",
        source_type=SourceType.TORRENT,
        subtitles=[SubtitleTrack(id="1", url="https://example.com/sub.vtt", lang="eng", format="vtt")],
    )
    http_stream = StreamSource(
        id="http1",
        provider="generic",
        release_title="Inception.Web.Stream",
        url="https://example.com/stream.mp4",
        source_type=SourceType.HTTP,
        subtitles=[SubtitleTrack(id="1", url="https://example.com/sub.srt", lang="spa", format="srt")],
    )

    # Torrent stream keyboard has Magnet buttons and Subtitles button
    kb_tor = stream_action_keyboard("tt1375666", torrent_stream)
    tor_texts = [b.text for row in kb_tor.inline_keyboard for b in row]
    assert any("Get Magnet URI" in t for t in tor_texts)
    assert any("Send .magnet File" in t for t in tor_texts)
    assert any("Subtitles" in t for t in tor_texts)
    assert not any("Download File" in t or "Start Download" in t for t in tor_texts)

    # HTTP stream keyboard has Subtitles button, but NO Download button whatsoever
    kb_http = stream_action_keyboard("tt1375666", http_stream)
    http_texts = [b.text for row in kb_http.inline_keyboard for b in row]
    assert not any("Magnet" in t for t in http_texts)
    assert not any("Download" in t for t in http_texts)
    assert any("Subtitles" in t for t in http_texts)
