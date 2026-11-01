"""Automated tests for search relevance ranking, typo tolerance, visual metadata, and Telegram UI workflows."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from aiogram.types import CallbackQuery, Message
from media_aggregator.bot.callbacks import (
    EpisodeCallback,
    MediaCallback,
    SearchCallback,
    SeasonCallback,
    StreamCallback,
)
from media_aggregator.bot.handlers.media import (
    handle_episode_streams,
    handle_media_view,
    handle_season_episodes,
    handle_seasons_view,
    handle_stream_detail_view,
)
from media_aggregator.bot.handlers.search import handle_search_page, perform_search
from media_aggregator.bot.keyboards import (
    media_detail_keyboard,
    search_results_keyboard,
)
from media_aggregator.bot.ui_utils import (
    escape_markdown,
    format_media_caption,
    is_valid_image_url,
    render_media_card,
)
from media_aggregator.models import (
    EpisodeItem,
    MediaItem,
    MediaType,
    SourceType,
    StreamSource,
    UserRecord,
    UserSettings,
)
from media_aggregator.search import (
    ParsedQuery,
    merge_and_deduplicate_results,
    normalize_title,
    parse_search_query,
    rank_search_results,
    score_search_result,
    strip_articles,
)
from media_aggregator.services.media_service import MediaService
from media_aggregator.storage import StorageManager


# ============================================================================
# 1. Search Ranking Unit Tests
# ============================================================================

def test_ranking_breaking_bad():
    """Verify 'Breaking Bad' ranks #1 above spin-offs, movies, and partial matches."""
    pool = [
        MediaItem(id="tt1", title="Breaking Bad Habits", type=MediaType.MOVIE, year="2012", imdb_rating="5.2"),
        MediaItem(id="tt2", title="El Camino: A Breaking Bad Movie", type=MediaType.MOVIE, year="2019", imdb_rating="7.3"),
        MediaItem(
            id="tt0903747",
            title="Breaking Bad",
            type=MediaType.SERIES,
            year="2008-2013",
            imdb_rating="9.5",
            poster="https://images.metahub.space/poster/medium/tt0903747/img.jpg",
            synopsis="A high school chemistry teacher diagnosed with lung cancer turns to manufacturing methamphetamine.",
        ),
        MediaItem(id="tt3", title="Breaking Bad: Original Minisodes", type=MediaType.SERIES, year="2009", imdb_rating="6.8"),
        MediaItem(id="tt4", title="Bad Boys", type=MediaType.MOVIE, year="1995", imdb_rating="6.9"),
    ]

    ranked = rank_search_results(pool, query="Breaking Bad")
    assert len(ranked) == 5
    assert ranked[0].id == "tt0903747"
    assert ranked[0].title == "Breaking Bad"


def test_ranking_the_it_show():
    """Verify 'The It Show' returns closest relevant matches first, prioritizing exact & article matches."""
    pool = [
        MediaItem(id="m1", title="IT", type=MediaType.MOVIE, year="2017", imdb_rating="7.3"),
        MediaItem(id="m2", title="The It Show", type=MediaType.SERIES, year="2020", imdb_rating="6.5"),
        MediaItem(id="m3", title="It Chapter Two", type=MediaType.MOVIE, year="2019", imdb_rating="6.5"),
        MediaItem(id="m4", title="Show Dogs", type=MediaType.MOVIE, year="2018", imdb_rating="3.9"),
        MediaItem(id="m5", title="The Truman Show", type=MediaType.MOVIE, year="1998", imdb_rating="8.2"),
    ]

    ranked = rank_search_results(pool, query="The It Show")
    assert ranked[0].title == "The It Show"
    # "IT" or items with both "It" and "Show" should rank above completely unrelated "The Truman Show"
    top_titles = [item.title for item in ranked[:3]]
    assert "The It Show" in top_titles
    assert "IT" in top_titles


def test_ranking_exact_title_matches_above_partials():
    """Verify exact match always beats prefix, substring, and token overlap matches."""
    pool = [
        MediaItem(id="1", title="Matrix Reloaded", type=MediaType.MOVIE, year="2003"),
        MediaItem(id="2", title="The Matrix", type=MediaType.MOVIE, year="1999"),
        MediaItem(id="3", title="The Matrix Revolutions", type=MediaType.MOVIE, year="2003"),
        MediaItem(id="4", title="Matrix", type=MediaType.MOVIE, year="1993"),
    ]

    ranked = rank_search_results(pool, query="The Matrix")
    assert ranked[0].title == "The Matrix"


def test_ranking_fuzzy_misspellings_tolerance():
    """Verify typo tolerance ranks intended titles near the top."""
    pool = [
        MediaItem(id="tt0903747", title="Breaking Bad", type=MediaType.SERIES, year="2008"),
        MediaItem(id="tt1375666", title="Inception", type=MediaType.MOVIE, year="2010"),
        MediaItem(id="tt0816692", title="Interstellar", type=MediaType.MOVIE, year="2014"),
        MediaItem(id="tt9999999", title="Random Unrelated Film", type=MediaType.MOVIE, year="2021"),
    ]

    # Typo: "Breking Bad" -> "Breaking Bad"
    ranked_bb = rank_search_results(pool, query="Breking Bad")
    assert ranked_bb[0].title == "Breaking Bad"

    # Typo: "Inceptoin" -> "Inception"
    ranked_inc = rank_search_results(pool, query="Inceptoin")
    assert ranked_inc[0].title == "Inception"

    # Typo: "Interstelar" -> "Interstellar"
    ranked_int = rank_search_results(pool, query="Interstelar")
    assert ranked_int[0].title == "Interstellar"


def test_ranking_queries_with_release_years():
    """Verify query year bonus prioritizes matching release year."""
    pool = [
        MediaItem(id="sm1", title="Spider-Man", type=MediaType.MOVIE, year="2002", imdb_rating="7.4"),
        MediaItem(id="sm2", title="Spider-Man", type=MediaType.SERIES, year="1994", imdb_rating="8.4"),
        MediaItem(id="sm3", title="The Amazing Spider-Man", type=MediaType.MOVIE, year="2012", imdb_rating="6.9"),
        MediaItem(id="sm4", title="Spider-Man: No Way Home", type=MediaType.MOVIE, year="2021", imdb_rating="8.2"),
    ]

    # Query with year: "Spider-Man 2002"
    ranked_2002 = rank_search_results(pool, query="Spider-Man 2002")
    assert ranked_2002[0].id == "sm1"
    assert ranked_2002[0].year == "2002"

    # Query with year: "Spider-Man 1994"
    ranked_1994 = rank_search_results(pool, query="Spider-Man 1994")
    assert ranked_1994[0].id == "sm2"
    assert ranked_1994[0].year == "1994"


def test_ranking_media_type_keywords():
    """Verify query hints like 'movie' or 'series' prioritize matching media types."""
    pool = [
        MediaItem(id="av1", title="Avatar", type=MediaType.MOVIE, year="2009", imdb_rating="7.9"),
        MediaItem(id="av2", title="Avatar", type=MediaType.SERIES, year="2024", imdb_rating="8.0"),
    ]

    ranked_movie = rank_search_results(pool, query="Avatar movie")
    assert ranked_movie[0].id == "av1"
    assert ranked_movie[0].type == MediaType.MOVIE

    ranked_series = rank_search_results(pool, query="Avatar series")
    assert ranked_series[0].id == "av2"
    assert ranked_series[0].type == MediaType.SERIES


def test_duplicate_detection_and_merging():
    """Verify duplicate results from multiple providers are merged without losing metadata."""
    item_cinemeta = MediaItem(
        id="tt0903747",
        title="Breaking Bad",
        type=MediaType.SERIES,
        year="2008-2013",
        poster="https://img.metahub.space/tt0903747.jpg",
        synopsis="A high school chemistry teacher diagnosed with lung cancer.",
        genres=["Crime", "Drama"],
        imdb_rating="9.5",
    )
    item_other_provider = MediaItem(
        id="tt0903747",
        title="Breaking Bad",
        type=MediaType.SERIES,
        year="2008",
        director="Vince Gilligan",
        cast=["Bryan Cranston", "Aaron Paul"],
        episodes=[EpisodeItem(id="tt0903747:1:1", season=1, episode=1, title="Pilot")],
    )

    merged = merge_and_deduplicate_results([item_cinemeta, item_other_provider])
    assert len(merged) == 1
    m = merged[0]
    assert m.id == "tt0903747"
    assert m.poster == "https://img.metahub.space/tt0903747.jpg"
    assert m.director == "Vince Gilligan"
    assert "Bryan Cranston" in m.cast
    assert len(m.episodes) == 1
    assert m.imdb_rating == "9.5"


def test_pagination_and_ranking_consistency():
    """Verify globally ranked results maintain consistent ordering and no duplication across pages."""
    raw_items = [
        MediaItem(id=f"item_{i}", title=f"Film {i}", year=str(2000 + i), imdb_rating=str(5.0 + (i * 0.2)))
        for i in range(12)
    ]
    ranked = rank_search_results(raw_items, query="Film")

    page_size = 5
    page_0 = ranked[0:5]
    page_1 = ranked[5:10]
    page_2 = ranked[10:12]

    # No overlap
    ids_0 = {item.id for item in page_0}
    ids_1 = {item.id for item in page_1}
    ids_2 = {item.id for item in page_2}

    assert ids_0.isdisjoint(ids_1)
    assert ids_1.isdisjoint(ids_2)
    assert len(ids_0) + len(ids_1) + len(ids_2) == 12


# ============================================================================
# 2. Visual Metadata & Formatting Tests
# ============================================================================

def test_visual_metadata_valid_poster_url():
    """Verify format_media_caption and is_valid_image_url with HTTPS poster URLs."""
    valid_url = "https://images.metahub.space/poster/medium/tt0903747/img.jpg"
    assert is_valid_image_url(valid_url) is True

    item = MediaItem(
        id="tt0903747",
        title="Breaking Bad",
        type=MediaType.SERIES,
        year="2008-2013",
        imdb_rating="9.5",
        runtime="47 min",
        genres=["Crime", "Drama"],
        poster=valid_url,
        synopsis="A chemistry teacher turns to meth manufacturing.",
    )

    caption = format_media_caption(item)
    assert "Breaking Bad" in caption
    assert "⭐ IMDb: 9.5/10" in caption
    assert "⏳ 47 min" in caption
    assert "Crime, Drama" in caption
    assert "Synopsis" in caption
    assert len(caption) <= 1024


def test_visual_metadata_missing_and_invalid_images():
    """Verify graceful handling when poster is missing or invalid."""
    assert is_valid_image_url(None) is False
    assert is_valid_image_url("") is False
    assert is_valid_image_url("file:///etc/passwd") is False
    assert is_valid_image_url("invalid_url_text") is False

    item = MediaItem(
        id="tt111",
        title="No Poster Movie",
        type=MediaType.MOVIE,
        year=None,
        synopsis=None,
    )
    caption = format_media_caption(item)
    assert "No Poster Movie" in caption
    assert "Movie" in caption


@pytest.mark.asyncio
async def test_render_media_card_link_preview_options():
    """Verify render_media_card attaches LinkPreviewOptions with prefer_large_media and show_above_text."""
    msg = AsyncMock()
    item = MediaItem(
        id="tt999",
        title="Visual Film",
        poster="https://images.metahub.space/poster/medium/tt999/img.jpg",
    )
    kb = search_results_keyboard(results=[item], query="Visual Film", page=0)

    await render_media_card(msg, item=item, caption="Test Caption", reply_markup=kb)

    assert msg.edit_text.called
    kwargs = msg.edit_text.call_args[1]
    assert "link_preview_options" in kwargs
    lp = kwargs["link_preview_options"]
    assert lp.url == item.poster
    assert lp.prefer_large_media is True
    assert lp.show_above_text is True


@pytest.mark.asyncio
async def test_render_media_card_fallback_on_missing_poster():
    """Verify render_media_card sets is_disabled=True when item has no poster."""
    msg = AsyncMock()
    item = MediaItem(id="tt000", title="Plain Film", poster=None)
    kb = search_results_keyboard(results=[item], query="Plain Film", page=0)

    await render_media_card(msg, item=item, caption="Plain Caption", reply_markup=kb)

    assert msg.edit_text.called
    kwargs = msg.edit_text.call_args[1]
    lp = kwargs["link_preview_options"]
    assert lp.is_disabled is True


# ============================================================================
# 3. Integration: Search-to-Stream Workflow Tests
# ============================================================================

@pytest.mark.asyncio
async def test_search_interaction_navigation_and_pagination(tmp_path):
    """Verify search execution, card presentation, and page turns."""
    storage = StorageManager(db_path=tmp_path / "test_interaction.db")
    cinemeta_mock = MagicMock()

    # Create 8 search items
    items = [
        MediaItem(
            id=f"tt00{i}",
            title=f"Breaking Bad Special {i}",
            type=MediaType.SERIES,
            year="2009",
            imdb_rating="8.0",
            poster=f"https://img.metahub.space/tt00{i}.jpg",
            synopsis=f"Synopsis for special {i}",
        )
        for i in range(8)
    ]
    # Featured main series
    items.insert(
        0,
        MediaItem(
            id="tt0903747",
            title="Breaking Bad",
            type=MediaType.SERIES,
            year="2008-2013",
            imdb_rating="9.5",
            poster="https://img.metahub.space/tt0903747.jpg",
            synopsis="A high school chemistry teacher diagnosed with lung cancer.",
        ),
    )
    cinemeta_mock.search.return_value = items
    media_service = MediaService(storage=storage, cinemeta=cinemeta_mock)
    user = UserRecord(user_id=101, username="binge_watcher")

    # Step 1: Initial search
    msg = MagicMock(spec=Message)
    status_msg = AsyncMock()
    msg.answer = AsyncMock(return_value=status_msg)

    await perform_search(msg, query="Breaking Bad", media_service=media_service, user_record=user)

    assert status_msg.edit_text.called
    result_text = status_msg.edit_text.call_args[0][0]
    assert "Found **9** matches" in result_text
    assert "Breaking Bad" in result_text
    assert "Page 1/2" in result_text

    # Step 2: Navigate to Page 2
    cb_page = AsyncMock()
    cb_page.message = AsyncMock()
    await handle_search_page(cb_page, SearchCallback(query="Breaking Bad", page=1), media_service)

    assert cb_page.message.edit_text.called
    page2_text = cb_page.message.edit_text.call_args[0][0]
    assert "Page 2/2" in page2_text


@pytest.mark.asyncio
async def test_search_to_details_seasons_episodes_streams_flow(tmp_path):
    """Verify complete uninterrupted user journey from search to stream discovery."""
    storage = StorageManager(db_path=tmp_path / "test_flow.db")
    cinemeta_mock = MagicMock()

    episodes = [
        EpisodeItem(id="tt0903747:1:1", season=1, episode=1, title="Pilot"),
        EpisodeItem(id="tt0903747:1:2", season=1, episode=2, title="Cat's in the Bag..."),
    ]
    bb_item = MediaItem(
        id="tt0903747",
        title="Breaking Bad",
        type=MediaType.SERIES,
        year="2008-2013",
        imdb_rating="9.5",
        poster="https://img.metahub.space/tt0903747.jpg",
        synopsis="A high school chemistry teacher diagnosed with lung cancer turns to manufacturing methamphetamine.",
        genres=["Crime", "Drama"],
        episodes=episodes,
    )

    cinemeta_mock.search.return_value = [bb_item]
    cinemeta_mock.get_metadata.return_value = bb_item

    media_service = MediaService(storage=storage, cinemeta=cinemeta_mock)
    user = UserRecord(user_id=42, username="walter_white")

    # 1. Search
    msg = MagicMock(spec=Message)
    status_msg = AsyncMock()
    msg.answer = AsyncMock(return_value=status_msg)
    await perform_search(msg, query="Breaking Bad", media_service=media_service, user_record=user)
    assert status_msg.edit_text.called

    # 2. View details
    cb_detail = AsyncMock()
    cb_detail.message = AsyncMock()
    await handle_media_view(cb_detail, MediaCallback(id="tt0903747", action="view"), media_service, user)
    assert cb_detail.message.edit_text.called
    assert "Breaking Bad" in cb_detail.message.edit_text.call_args[0][0]

    # 3. View seasons
    cb_seasons = AsyncMock()
    cb_seasons.message = AsyncMock()
    await handle_seasons_view(cb_seasons, MediaCallback(id="tt0903747", action="seasons"), media_service)
    assert cb_seasons.message.edit_text.called
    assert "Select a season" in cb_seasons.message.edit_text.call_args[0][0]

    # 4. View episodes in season 1
    cb_episodes = AsyncMock()
    cb_episodes.message = AsyncMock()
    await handle_season_episodes(cb_episodes, SeasonCallback(id="tt0903747", season=1), media_service)
    assert cb_episodes.message.edit_text.called
    assert "Season 1" in cb_episodes.message.edit_text.call_args[0][0]

    # 5. Resolve streams for S01E01
    cb_streams = AsyncMock()
    cb_streams.message = AsyncMock()
    mock_streams = [
        StreamSource(
            id="st_1080p",
            provider="Torrentio",
            release_title="Breaking.Bad.S01E01.1080p.BluRay.x264",
            resolution="1080p",
            seeders=120,
            size_display="1.8 GB",
            info_hash="0123456789abcdef0123456789abcdef01234567",
        )
    ]
    with patch.object(media_service, "get_streams", return_value=mock_streams):
        await handle_episode_streams(
            cb_streams,
            EpisodeCallback(id="tt0903747", season=1, episode=1),
            media_service,
            user,
        )
        assert cb_streams.message.edit_text.called
        assert "stream sources" in cb_streams.message.edit_text.call_args[0][0]

    # 6. View stream details
    cb_stream_detail = AsyncMock()
    cb_stream_detail.message = AsyncMock()
    with patch.object(media_service, "get_streams", return_value=mock_streams):
        await handle_stream_detail_view(
            cb_stream_detail,
            StreamCallback(id="tt0903747", season=1, episode=1, idx=0, action="view"),
            media_service,
            user,
        )
        assert cb_stream_detail.message.edit_text.called
        assert "Stream Source Information" in cb_stream_detail.message.edit_text.call_args[0][0]


# ============================================================================
# 4. Strict Exact Match Immunity, Aliases, Diversity & Resilience Tests
# ============================================================================

def test_ranking_exact_match_cannot_be_outranked_by_partial_matches():
    """Verify mathematically that an exact title match CANNOT be outranked by partial matches.
    
    Even if the partial match has:
      - Perfect matching year (+150 pts)
      - Perfect matching media type (+100 pts)
      - Perfect 10.0 IMDb rating (+40 pts)
      - Poster (+15 pts)
      - Synopsis (+10 pts)
      - 50 Episodes (+15 pts)
    And the exact match has:
      - 1.0 IMDb rating (+4 pts)
      - No poster, no synopsis, no episodes
      - Mismatching year (-100 pts)
    The exact match must still win by thousands of points.
    """
    exact_item_worst_case = MediaItem(
        id="tt_exact",
        title="Dune",
        type=MediaType.MOVIE,
        year="1984",
        imdb_rating="1.0",
        poster=None,
        synopsis=None,
    )
    partial_item_best_case = MediaItem(
        id="tt_partial",
        title="Dune: Part Two and Beyond The Universe",
        type=MediaType.MOVIE,
        year="2024",
        imdb_rating="10.0",
        poster="https://img.metahub.space/dune2.jpg",
        synopsis="A comprehensive detailed synopsis of the galactic desert world.",
        episodes=[EpisodeItem(id=f"ep{i}", season=1, episode=i) for i in range(50)],
    )

    query = "Dune 2024 movie"
    ranked = rank_search_results([partial_item_best_case, exact_item_worst_case], query=query)

    assert ranked[0].id == "tt_exact"
    assert ranked[0].title == "Dune"
    assert ranked[1].id == "tt_partial"


def test_ranking_original_localized_and_alternate_titles():
    """Verify searching by original, localized, or alternate titles resolves the target item."""
    item = MediaItem(
        id="tt0245429",
        title="Spirited Away",
        original_title="Sen to Chihiro no Kamikakushi",
        aliases=["Sen and Chihiro", "Le Voyage de Chihiro"],
        type=MediaType.MOVIE,
        year="2001",
        imdb_rating="8.6",
    )
    other = MediaItem(id="tt99", title="Some Random Movie", type=MediaType.MOVIE, year="2020")

    # Search by original Japanese Romanized title
    ranked_orig = rank_search_results([other, item], query="Sen to Chihiro no Kamikakushi")
    assert ranked_orig[0].id == "tt0245429"
    assert ranked_orig[0].title == "Spirited Away"

    # Search by English alias
    ranked_alias = rank_search_results([other, item], query="Sen and Chihiro")
    assert ranked_alias[0].id == "tt0245429"

    # Search by French localized title
    ranked_fr = rank_search_results([other, item], query="Le Voyage de Chihiro")
    assert ranked_fr[0].id == "tt0245429"


def test_search_special_characters_and_empty_queries():
    """Verify empty queries and punctuation-only queries return cleanly without exceptions."""
    pool = [MediaItem(id="tt1", title="Batman", type=MediaType.MOVIE)]

    assert rank_search_results(pool, query="") == []
    assert rank_search_results(pool, query="   ") == []
    assert rank_search_results(pool, query="!@#$%^&*()_+{}[]:;\"'<>?,./") == []
    assert rank_search_results([], query="Batman") == []


def test_provider_diversity_on_page_one():
    """Verify that provider diversity ensures high-quality results from different providers reach page 1."""
    # 8 items from Cinemeta / IMDb prefix 'tt'
    tt_items = [
        MediaItem(id=f"tt00{i}", title=f"Naruto Shippuden Film {i}", type=MediaType.MOVIE, year=str(2005 + i), imdb_rating="7.0")
        for i in range(8)
    ]
    # 1 item from Kitsu anime prefix 'kitsu:11'
    kitsu_item = MediaItem(id="kitsu:11", title="Naruto Shippuden", type=MediaType.ANIME, year="2007", imdb_rating="8.7")

    pool = tt_items + [kitsu_item]
    ranked = rank_search_results(pool, query="Naruto Shippuden")

    # The top 5 items (page 1) must contain the exact kitsu anime series match
    page_1_ids = [item.id for item in ranked[:5]]
    assert "kitsu:11" in page_1_ids


@pytest.mark.asyncio
async def test_provider_timeouts_failures_and_rate_limits(tmp_path):
    """Verify graceful handling when primary discovery provider times out or triggers 429 rate limit."""
    storage = StorageManager(db_path=tmp_path / "test_timeouts.db")
    cinemeta_mock = MagicMock()
    cinemeta_mock.search.side_effect = TimeoutError("Cinemeta gateway connection timed out")

    media_service = MediaService(storage=storage, cinemeta=cinemeta_mock)

    # Should not crash, should return empty list or fallback results
    results = await media_service.search("Interstellar")
    assert results == []


@pytest.mark.asyncio
async def test_stable_pagination_when_provider_fails_on_later_page(tmp_path):
    """Verify that cached search results guarantee stable pagination even if providers fail afterwards."""
    storage = StorageManager(db_path=tmp_path / "test_stable_pages.db")
    cinemeta_mock = MagicMock()

    mock_items = [
        MediaItem(id=f"tt_page_{i}", title=f"Star Wars Episode {i}", year=str(1977 + i))
        for i in range(12)
    ]
    cinemeta_mock.search.return_value = mock_items

    media_service = MediaService(storage=storage, cinemeta=cinemeta_mock)

    # First call (populates cache)
    results_page_0 = await media_service.search("Star Wars")
    assert len(results_page_0) == 12

    # Provider now goes offline
    cinemeta_mock.search.side_effect = ConnectionRefusedError("Provider servers offline")

    # Second call (e.g. user browsing to page 1)
    results_page_1 = await media_service.search("Star Wars")
    assert len(results_page_1) == 12
    assert [x.id for x in results_page_1] == [x.id for x in results_page_0]

