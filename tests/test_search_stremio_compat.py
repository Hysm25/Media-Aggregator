"""Comprehensive tests for search fixes, Stremio protocol compatibility, and Telegram workflow."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import requests
from aiogram.types import CallbackQuery, Message, User
from media_aggregator.bot.callbacks import EpisodeCallback, MediaCallback, SearchCallback, SeasonCallback, StreamCallback
from media_aggregator.bot.handlers.media import handle_episode_streams, handle_media_view, handle_season_episodes, handle_seasons_view, handle_stream_detail_view
from media_aggregator.bot.handlers.search import escape_markdown, handle_search_command, handle_search_page, handle_text_search, perform_search
from media_aggregator.models import EpisodeItem, MediaItem, MediaType, SourceType, StreamSource, UserRecord, UserSettings
from media_aggregator.parser import parse_generic_stream
from media_aggregator.providers.base import BaseProvider
from media_aggregator.providers.cinemeta import CinemetaProvider
from media_aggregator.providers.generic import GenericStremioProvider
from media_aggregator.providers.registry import ProviderRegistry
from media_aggregator.providers.torrentio import TorrentioProvider
from media_aggregator.services.media_service import MediaService
from media_aggregator.storage import StorageManager


def test_cinemeta_search_none_type_regression():
    """Regression test: cinemeta.search with media_type=None must not crash with AttributeError."""
    provider = CinemetaProvider()

    mock_movie_resp = MagicMock()
    mock_movie_resp.status_code = 200
    mock_movie_resp.json.return_value = {
        "metas": [
            {"id": "tt100", "name": "Movie 1", "type": "movie", "year": "2020"},
        ]
    }

    mock_series_resp = MagicMock()
    mock_series_resp.status_code = 200
    mock_series_resp.json.return_value = {
        "metas": [
            {"id": "tt200", "name": "Series 1", "type": "series", "releaseInfo": "2018-2022"},
        ]
    }

    def _mock_get(url, **kwargs):
        if "/catalog/movie/" in url:
            return mock_movie_resp
        return mock_series_resp

    with patch.object(provider.session, "get", side_effect=_mock_get):
        # Must execute cleanly without raising AttributeError
        results = provider.search("Test Title", media_type=None)

    assert len(results) == 2
    assert results[0].id == "tt100"
    assert results[0].type == MediaType.MOVIE
    assert results[1].id == "tt200"
    assert results[1].type == MediaType.SERIES
    assert results[1].year == "2018-2022"


def test_cinemeta_get_metadata_flexible_signatures():
    """Verify get_metadata supports both (media_type, media_id) and (media_id, media_type) conventions."""
    provider = CinemetaProvider()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "meta": {
            "id": "tt0133093",
            "name": "The Matrix",
            "type": "movie",
            "year": "1999",
            "description": "A reality hacker movie.",
            "genres": ["Action", "Sci-Fi"],
        }
    }

    with patch.object(provider.session, "get", return_value=mock_resp):
        # 1. Positional (media_id, media_type)
        item1 = provider.get_metadata("tt0133093", media_type=MediaType.MOVIE)
        assert item1 is not None
        assert item1.title == "The Matrix"

        # 2. Legacy positional (media_type, media_id)
        item2 = provider.get_metadata(MediaType.MOVIE, "tt0133093")
        assert item2 is not None
        assert item2.title == "The Matrix"

        # 3. None media_type (auto-probes)
        item3 = provider.get_metadata("tt0133093")
        assert item3 is not None
        assert item3.title == "The Matrix"


def test_search_network_errors_and_timeouts():
    """Ensure network timeouts, 500 errors, and invalid JSON don't crash search."""
    provider = CinemetaProvider()

    # Timeout
    with patch.object(provider.session, "get", side_effect=requests.exceptions.Timeout("Timeout")):
        assert provider.search("Timeout Title", media_type=MediaType.MOVIE) == []

    # 500 Server Error
    mock_500 = MagicMock()
    mock_500.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
    with patch.object(provider.session, "get", return_value=mock_500):
        assert provider.search("500 Title", media_type=MediaType.MOVIE) == []

    # Invalid JSON
    mock_bad_json = MagicMock()
    mock_bad_json.status_code = 200
    mock_bad_json.json.side_effect = ValueError("Invalid JSON")
    with patch.object(provider.session, "get", return_value=mock_bad_json):
        assert provider.search("Bad JSON", media_type=MediaType.MOVIE) == []


def test_escape_markdown():
    """Verify special character escaping for Telegram legacy Markdown."""
    assert escape_markdown("Hunter_x_Hunter") == r"Hunter\_x\_Hunter"
    assert escape_markdown("*bold* and `code` [link]") == r"\*bold\* and \`code\` \[link\]"
    assert escape_markdown("") == ""
    assert escape_markdown(None) == ""  # type: ignore


@pytest.mark.asyncio
async def test_perform_search_markdown_safety_and_error_handling(tmp_path):
    """Test perform_search handles markdown escaping and exceptions safely."""
    storage = StorageManager(db_path=tmp_path / "test_search_safety.db")
    media_service = MediaService(storage=storage)
    user_record = UserRecord(user_id=1, full_name="Tester")

    msg = MagicMock(spec=Message)
    status_msg = AsyncMock()
    msg.answer = AsyncMock(return_value=status_msg)

    # 1. Search with special markdown characters in query
    with patch.object(media_service, "search", return_value=[]):
        await perform_search(msg, "Spider-Man: No_Way_Home [2021] *special*", media_service, user_record)
        # Message answer should escape characters in query
        call_text = msg.answer.call_args[0][0]
        assert r"No\_Way\_Home" in call_text
        assert r"\[2021\]" in call_text

    # 2. Search raises unexpected exception
    with patch.object(media_service, "search", side_effect=RuntimeError("Provider connection pool dead")):
        await perform_search(msg, "Failure Query", media_service, user_record)
        # Status message must be edited with friendly warning, not crash
        assert "An error occurred while searching" in status_msg.edit_text.call_args[0][0]


def test_stremio_id_prefixes_capability():
    """Verify provider idPrefixes filtering conformance."""
    cinemeta = CinemetaProvider()
    assert cinemeta.supports_id_prefix("tt1234567") is True
    assert cinemeta.supports_id_prefix("kitsu:1234") is False

    torrentio = TorrentioProvider()
    assert torrentio.supports_id_prefix("tt1234567") is True
    assert torrentio.supports_id_prefix("kitsu:1234") is True
    assert torrentio.supports_id_prefix("yt:1234") is False

    generic_open = GenericStremioProvider(name="Open", base_url="http://open.example")
    assert generic_open.supports_id_prefix("anything") is True


def test_stremio_stream_magnet_and_youtube_parsing():
    """Verify parsing streams with magnet externalUrl or YouTube ytId."""
    # Magnet link in externalUrl
    raw_magnet = {
        "name": "MediaFusion",
        "title": "Oppenheimer.2023.1080p.BluRay.x264\n1080p 👤 55 💾 4.5 GB",
        "externalUrl": "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Oppenheimer&so=2",
        "sources": ["tracker:udp://tracker.opentrackr.org:1337/announce"],
    }
    stream_magnet = parse_generic_stream(raw_magnet, provider_name="MediaFusion")
    assert stream_magnet.source_type == SourceType.TORRENT
    assert stream_magnet.info_hash == "0123456789abcdef0123456789abcdef01234567"
    assert stream_magnet.file_idx == 2
    assert stream_magnet.seeders == 55
    assert stream_magnet.size_display == "4.5 GB"
    assert "udp://tracker.opentrackr.org:1337/announce" in stream_magnet.trackers

    # YouTube ytId stream
    raw_yt = {
        "name": "YouTube Trailers",
        "title": "Official Trailer",
        "ytId": "uYPbbksJxIg",
    }
    stream_yt = parse_generic_stream(raw_yt, provider_name="YouTube")
    assert stream_yt.source_type == SourceType.HTTP
    assert stream_yt.url == "https://www.youtube.com/watch?v=uYPbbksJxIg"


@pytest.mark.asyncio
async def test_complete_telegram_search_to_stream_flow(tmp_path):
    """End-to-end integration test: Telegram Search -> Media View -> Seasons -> Episode -> Streams."""
    storage = StorageManager(db_path=tmp_path / "test_e2e_flow.db")
    cinemeta_mock = MagicMock(spec=CinemetaProvider)

    # 1. Mock search response with both Movie and TV Series
    cinemeta_mock.search.return_value = [
        MediaItem(id="tt0903747", title="Breaking Bad", type=MediaType.SERIES, year="2008-2013"),
        MediaItem(id="tt1375666", title="Inception", type=MediaType.MOVIE, year="2010"),
    ]

    # 2. Mock metadata response for Breaking Bad
    episodes = [
        EpisodeItem(id="tt0903747:1:1", season=1, episode=1, title="Pilot"),
        EpisodeItem(id="tt0903747:1:2", season=1, episode=2, title="Cat's in the Bag..."),
    ]
    cinemeta_mock.get_metadata.return_value = MediaItem(
        id="tt0903747",
        title="Breaking Bad",
        type=MediaType.SERIES,
        year="2008-2013",
        synopsis="A high school chemistry teacher diagnosed with lung cancer turns to manufacturing methamphetamine.",
        genres=["Crime", "Drama", "Thriller"],
        episodes=episodes,
    )

    media_service = MediaService(storage=storage, cinemeta=cinemeta_mock)
    user = UserRecord(user_id=123, full_name="Streamer", settings=UserSettings())

    # Step A: Perform search
    msg = MagicMock(spec=Message)
    status_msg = AsyncMock()
    msg.answer = AsyncMock(return_value=status_msg)
    await perform_search(msg, "Breaking Bad", media_service, user)

    assert status_msg.edit_text.called
    result_text = status_msg.edit_text.call_args[0][0]
    assert "Found **2** matches" in result_text

    # Step B: View media details
    cb_view = AsyncMock()
    cb_view.message = AsyncMock()
    await handle_media_view(cb_view, MediaCallback(id="tt0903747", action="view"), media_service, user)
    detail_text = cb_view.message.edit_text.call_args[0][0]
    assert "Breaking Bad" in detail_text
    assert "Crime, Drama, Thriller" in detail_text

    # Step C: View seasons
    cb_seasons = AsyncMock()
    cb_seasons.message = AsyncMock()
    await handle_seasons_view(cb_seasons, MediaCallback(id="tt0903747", action="seasons"), media_service)
    assert cb_seasons.message.edit_text.called

    # Step D: View season episodes
    cb_episodes = AsyncMock()
    cb_episodes.message = AsyncMock()
    await handle_season_episodes(cb_episodes, SeasonCallback(id="tt0903747", season=1), media_service)
    assert cb_episodes.message.edit_text.called

    # Step E: View episode streams
    cb_streams = AsyncMock()
    cb_streams.message = AsyncMock()
    mock_streams = [
        StreamSource(
            id="s1",
            provider="Torrentio",
            name="Torrentio\n1080p",
            title="Breaking.Bad.S01E01.1080p.BluRay\n👤 45 💾 1.5 GB",
            release_title="Breaking.Bad.S01E01.1080p.BluRay",
            info_hash="abcdef1234567890abcdef1234567890abcdef12",
            resolution="1080p",
            seeders=45,
            size_display="1.5 GB",
        )
    ]
    with patch.object(media_service, "get_streams", return_value=mock_streams):
        await handle_episode_streams(cb_streams, EpisodeCallback(id="tt0903747", season=1, episode=1), media_service, user)
        assert "Found **1** stream sources" in cb_streams.message.edit_text.call_args[0][0]

    # Step F: View stream details
    cb_stream_detail = AsyncMock()
    cb_stream_detail.message = AsyncMock()
    with patch.object(media_service, "get_streams", return_value=mock_streams):
        await handle_stream_detail_view(
            cb_stream_detail,
            StreamCallback(id="tt0903747", season=1, episode=1, idx=0, action="view"),
            media_service,
            user,
        )
        detail_lines = cb_stream_detail.message.edit_text.call_args[0][0]
        assert "Stream Source Information" in detail_lines
        assert "Breaking.Bad.S01E01.1080p.BluRay" in detail_lines


def test_live_cinemeta_and_torrentio_integration():
    """Live verification against real Stremio add-on endpoints (skipped if offline)."""
    try:
        r = requests.get("https://v3-cinemeta.strem.io/manifest.json", timeout=3)
        if r.status_code != 200:
            pytest.skip("Cinemeta endpoint unreachable")
    except Exception:
        pytest.skip("No external network access available")

    # Live search
    cinemeta = CinemetaProvider()
    results = cinemeta.search("Inception")
    assert len(results) > 0
    match = next((m for m in results if m.id == "tt1375666"), None)
    assert match is not None
    assert "Inception" in match.title

    # Live metadata
    meta = cinemeta.get_metadata(media_id="tt1375666", media_type=MediaType.MOVIE)
    assert meta is not None
    assert meta.title == "Inception"
    assert meta.synopsis is not None

    # Live streams
    torrentio = TorrentioProvider()
    streams = torrentio.get_streams(media_type=MediaType.MOVIE, media_id="tt1375666")
    assert len(streams) > 0
    assert any(s.info_hash for s in streams)
