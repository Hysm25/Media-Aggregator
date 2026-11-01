"""Tests for Telegram bot configuration, keyboards, middlewares, and handlers."""

import os
import time
from unittest.mock import AsyncMock, MagicMock
import pytest
from aiogram.types import CallbackQuery, Message, User
from media_aggregator.bot.callbacks import (
    AddonCallback,
    AdminCallback,
    DownloadCallback,
    EpisodeCallback,
    MediaCallback,
    NavCallback,
    SearchCallback,
    SeasonCallback,
    SettingsCallback,
    StreamCallback,
)
from media_aggregator.bot.config import BotConfig
from media_aggregator.bot.handlers.addons import handle_add_addon_command, handle_addons_view, handle_toggle_addon
from media_aggregator.bot.handlers.admin import handle_admin_dashboard, handle_approve_user, handle_system_stats
from media_aggregator.bot.handlers.downloads import (
    format_bytes,
    format_progress_bar,
    format_speed,
    handle_cancel_download,
    handle_copy_magnet,
    handle_list_downloads,
    handle_refresh_download,
    handle_view_download,
)
from media_aggregator.bot.handlers.media import (
    handle_episode_streams,
    handle_media_view,
    handle_season_episodes,
    handle_seasons_view,
    handle_stream_detail_view,
    handle_toggle_bookmark,
)
from media_aggregator.bot.handlers.search import handle_search_command, handle_search_page, handle_text_search
from media_aggregator.bot.handlers.settings import handle_cycle_quality, handle_cycle_seeds, handle_toggle_cam
from media_aggregator.bot.handlers.start import handle_claim_admin, handle_help, handle_nav_home, handle_noop, handle_start
from media_aggregator.bot.keyboards import (
    addons_list_keyboard,
    admin_dashboard_keyboard,
    download_control_keyboard,
    downloads_list_keyboard,
    episodes_keyboard,
    first_time_setup_keyboard,
    main_menu_keyboard,
    media_detail_keyboard,
    search_results_keyboard,
    seasons_keyboard,
    settings_keyboard,
    stream_action_keyboard,
    streams_keyboard,
)
from media_aggregator.bot.middlewares.auth import AuthMiddleware
from media_aggregator.bot.middlewares.rate_limit import RateLimitMiddleware
from media_aggregator.models import (
    AddonConfig,
    DownloadRecord,
    DownloadStatus,
    EpisodeItem,
    MediaItem,
    MediaType,
    SourceType,
    StreamSource,
    UserRecord,
    UserSettings,
)
from media_aggregator.services.addon_service import AddonService
from media_aggregator.services.download_service import DownloadService
from media_aggregator.services.user_service import UserService
from media_aggregator.storage import StorageManager


def test_bot_config():
    cfg = BotConfig(bot_token="test_token_123", admin_ids=[9999])
    assert cfg.bot_token == "test_token_123"
    assert 9999 in cfg.admin_ids


def test_format_helpers():
    assert "25.0%" in format_progress_bar(25.0)
    assert format_bytes(500) == "500 B"
    assert "MB" in format_bytes(5 * 1024 * 1024)
    assert "GB" in format_bytes(2 * 1024 * 1024 * 1024)
    assert "/s" in format_speed(1024 * 1024)


def test_all_keyboards():
    # Main menu
    kb_user = main_menu_keyboard(is_admin=False)
    assert len(kb_user.inline_keyboard) == 3
    kb_admin = main_menu_keyboard(is_admin=True)
    assert len(kb_admin.inline_keyboard) == 4

    # Search results
    items = [
        MediaItem(id="tt1", title="Item 1", type=MediaType.MOVIE, year="2020"),
        MediaItem(id="tt2", title="Item 2", type=MediaType.SERIES, year="2021"),
    ]
    kb_srch = search_results_keyboard(items, query="test", page=0)
    assert len(kb_srch.inline_keyboard) >= 3

    # Media detail
    kb_detail_movie = media_detail_keyboard(items[0], is_bookmarked=False)
    assert any("Find Movie Streams" in btn.text for row in kb_detail_movie.inline_keyboard for btn in row)
    kb_detail_series = media_detail_keyboard(items[1], is_bookmarked=True)
    assert any("Browse Seasons" in btn.text for row in kb_detail_series.inline_keyboard for btn in row)

    # Seasons & Episodes
    kb_sn = seasons_keyboard("tt2", [1, 2, 3])
    assert len(kb_sn.inline_keyboard) >= 2
    eps = [EpisodeItem(id="tt2:1:1", season=1, episode=1, title="Pilot")]
    kb_ep = episodes_keyboard("tt2", 1, eps)
    assert len(kb_ep.inline_keyboard) >= 2

    # Streams
    streams = [
        StreamSource(
            id="s1",
            provider="torrentio",
            release_title="Matrix.1080p",
            resolution="1080p",
            size_display="2.5 GB",
            seeders=40,
            info_hash="aabbccddeeff00112233445566778899aabbccdd",
        )
    ]
    kb_st = streams_keyboard("tt1", streams)
    assert len(kb_st.inline_keyboard) >= 2
    kb_act = stream_action_keyboard("tt1", streams[0])
    assert any("Magnet" in btn.text for row in kb_act.inline_keyboard for btn in row)

    # Downloads
    dls = [
        DownloadRecord(
            id=1,
            media_id="tt1",
            media_title="Download 1",
            status=DownloadStatus.DOWNLOADING,
            progress_percent=45.0,
            target_url="http://example.com/1",
        )
    ]
    kb_dl = downloads_list_keyboard(dls)
    assert len(kb_dl.inline_keyboard) >= 2
    kb_ctrl = download_control_keyboard(1, is_active=True)
    assert any("Cancel Download" in btn.text for row in kb_ctrl.inline_keyboard for btn in row)

    # Settings & Addons
    kb_cfg = settings_keyboard(UserSettings())
    assert len(kb_cfg.inline_keyboard) >= 4
    addons = [AddonConfig(id="a1", name="Addon 1", manifest_url="http://x", base_url="http://x", enabled=True)]
    kb_adn = addons_list_keyboard(addons)
    assert len(kb_adn.inline_keyboard) >= 2

    # Admin & Setup
    users = [UserRecord(user_id=888, username="test_u", is_allowed=False)]
    kb_adm = admin_dashboard_keyboard(users)
    assert any("Approve" in btn.text for row in kb_adm.inline_keyboard for btn in row)
    kb_setup = first_time_setup_keyboard()
    assert any("Claim" in btn.text for row in kb_setup.inline_keyboard for btn in row)


@pytest.mark.asyncio
async def test_auth_middleware(tmp_path):
    storage = StorageManager(db_path=tmp_path / "test_auth_mw.db")
    user_service = UserService(storage=storage)
    config = BotConfig(bot_token="test", admin_ids=[777])
    middleware = AuthMiddleware(user_service=user_service, config=config)

    handler = AsyncMock(return_value="OK")
    event = MagicMock(spec=Message)
    event.text = "/start"
    event.answer = AsyncMock()

    # 1. Untrusted user (id=100) cannot claim admin or access bot in personal mode
    data_untrusted = {"event_from_user": User(id=100, is_bot=False, first_name="UntrustedUser")}
    res_untrusted = await middleware(handler, event, data_untrusted)
    assert res_untrusted is None
    event.answer.assert_called()

    # 2. Trusted admin in admin_ids (id=777) is granted access and made admin
    data_admin = {"event_from_user": User(id=777, is_bot=False, first_name="StaticAdmin")}
    res_admin = await middleware(handler, event, data_admin)
    assert res_admin == "OK"
    assert data_admin["user_record"].is_admin is True

    # 3. Multi-user mode allows non-admin users to browse
    config_multi = BotConfig(bot_token="test", admin_ids=[777], bot_mode="multi-user")
    mw_multi = AuthMiddleware(user_service=user_service, config=config_multi)
    data_guest = {"event_from_user": User(id=200, is_bot=False, first_name="GuestUser")}
    res_guest = await mw_multi(handler, event, data_guest)
    assert res_guest == "OK"
    assert data_guest["user_record"].is_admin is False


@pytest.mark.asyncio
async def test_rate_limit_middleware():
    mw = RateLimitMiddleware(rate_limit_seconds=0.5)
    handler = AsyncMock(return_value="PASSED")
    event = MagicMock(spec=CallbackQuery)
    event.answer = AsyncMock()
    data = {"event_from_user": User(id=123, is_bot=False, first_name="User")}

    # First call succeeds
    res1 = await mw(handler, event, data)
    assert res1 == "PASSED"

    # Rapid second call is throttled
    res2 = await mw(handler, event, data)
    assert res2 is None
    event.answer.assert_called_with("⏳ Please slow down.", show_alert=False)


@pytest.mark.asyncio
async def test_start_and_claim_handlers(tmp_path):
    storage = StorageManager(db_path=tmp_path / "test_handlers_start.db")
    user_service = UserService(storage=storage)

    # /start in setup mode
    msg = AsyncMock()
    user_rec = UserRecord(user_id=1, username="u1")
    await handle_start(msg, user_record=user_rec, is_setup_mode=True)
    msg.answer.assert_called_once()
    assert "no registered administrators" in msg.answer.call_args[0][0]

    # /start in normal mode
    msg_normal = AsyncMock()
    await handle_start(msg_normal, user_record=user_rec, is_setup_mode=False)
    assert "Welcome" in msg_normal.answer.call_args[0][0]

    # handle_claim_admin with unauthorized user
    cfg = BotConfig(admin_ids=[1])
    cb_unauth = AsyncMock()
    cb_unauth.from_user = User(id=999, is_bot=False, first_name="Hacker")
    cb_unauth.message = AsyncMock()
    await handle_claim_admin(cb_unauth, user_record=UserRecord(user_id=999), user_service=user_service, config=cfg)
    cb_unauth.answer.assert_called_with("🚫 Unauthorized: Your Telegram ID is not in TELEGRAM_ADMIN_IDS.", show_alert=True)
    assert await user_service.is_admin(999) is False

    # handle_claim_admin with authorized user
    cb = AsyncMock()
    cb.from_user = User(id=1, is_bot=False, first_name="U1")
    cb.message = AsyncMock()
    await handle_claim_admin(cb, user_record=user_rec, user_service=user_service, config=cfg)
    assert await user_service.is_admin(1) is True


@pytest.mark.asyncio
async def test_settings_handlers(tmp_path):
    storage = StorageManager(db_path=tmp_path / "test_handlers_settings.db")
    user_service = UserService(storage=storage)
    user = await user_service.get_or_create_user(50, username="settings_user")

    cb = AsyncMock()
    cb.message = AsyncMock()

    # Cycle quality
    await handle_cycle_quality(cb, user_record=user, user_service=user_service)
    assert user.settings.preferred_quality == "4K"

    # Toggle CAM
    assert user.settings.exclude_cam is True
    await handle_toggle_cam(cb, user_record=user, user_service=user_service)
    assert user.settings.exclude_cam is False

    # Cycle seeds
    await handle_cycle_seeds(cb, user_record=user, user_service=user_service)
    assert user.settings.min_seeders == 5


@pytest.mark.asyncio
async def test_admin_handlers(tmp_path):
    storage = StorageManager(db_path=tmp_path / "test_handlers_admin.db")
    user_service = UserService(storage=storage)
    admin_user = await user_service.get_or_create_user(999, username="boss")
    await user_service.claim_first_admin(999)
    admin_rec = await user_service.get_user(999)

    regular_user = await user_service.get_or_create_user(555, username="applicant")

    # Admin dashboard
    cb = MagicMock(spec=CallbackQuery)
    cb.message = AsyncMock()
    cb.answer = AsyncMock()
    await handle_admin_dashboard(cb, user_record=admin_rec, user_service=user_service)
    cb.message.edit_text.assert_called()

    # Approve user
    cb_approve = MagicMock(spec=CallbackQuery)
    cb_approve.message = AsyncMock()
    cb_approve.answer = AsyncMock()
    cb_approve.bot = None
    adm_cb_data = AdminCallback(action="approve", uid=555)
    await handle_approve_user(cb_approve, adm_cb_data, user_record=admin_rec, user_service=user_service)
    assert await user_service.is_authorized(555) is True

    # System stats
    cb_stats = MagicMock(spec=CallbackQuery)
    cb_stats.message = AsyncMock()
    cb_stats.answer = AsyncMock()
    await handle_system_stats(cb_stats, user_record=admin_rec, user_service=user_service)
    cb_stats.message.edit_text.assert_called()
    assert "System & Database Metrics" in cb_stats.message.edit_text.call_args[0][0]


@pytest.mark.asyncio
async def test_search_handlers():
    media_service = AsyncMock()
    media_service.search.return_value = [
        MediaItem(id="tt01", title="Found Movie", type=MediaType.MOVIE, year="2022")
    ]
    user = UserRecord(user_id=1, username="u")

    # Command /search
    msg = AsyncMock()
    msg.text = "/search Matrix"
    status_msg = AsyncMock()
    msg.answer.return_value = status_msg
    await handle_search_command(msg, media_service=media_service, user_record=user)
    status_msg.edit_text.assert_called()
    assert "Found" in status_msg.edit_text.call_args[0][0]

    # Free text search
    msg_text = AsyncMock()
    msg_text.text = "Inception"
    msg_text.answer.return_value = status_msg
    await handle_text_search(msg_text, media_service=media_service, user_record=user)
    status_msg.edit_text.assert_called()


@pytest.mark.asyncio
async def test_media_handlers(tmp_path):
    storage = StorageManager(db_path=tmp_path / "test_handlers_media.db")
    media_service = MagicMock()
    media_service.storage = storage

    item = MediaItem(
        id="tt888",
        title="Sample Show",
        type=MediaType.SERIES,
        synopsis="A great TV series",
        episodes=[
            EpisodeItem(id="tt888:1:1", season=1, episode=1, title="Ep 1"),
            EpisodeItem(id="tt888:1:2", season=1, episode=2, title="Ep 2"),
        ],
    )
    media_service.get_details = AsyncMock(return_value=item)
    media_service.get_streams = AsyncMock(return_value=[
        StreamSource(
            id="st1",
            provider="torrentio",
            release_title="Sample.Show.S01E01.1080p",
            resolution="1080p",
            size_display="1.2 GB",
            seeders=30,
            info_hash="aabbccddeeff00112233445566778899aabbccdd",
        )
    ])

    user = UserRecord(user_id=2, username="u2")

    # View media
    cb = MagicMock(spec=CallbackQuery)
    cb.message = AsyncMock()
    cb.answer = AsyncMock()
    await handle_media_view(cb, MediaCallback(id="tt888", action="view"), media_service, user)
    cb.message.edit_text.assert_called()
    assert "Sample Show" in cb.message.edit_text.call_args[0][0]

    # Bookmark toggle
    await handle_toggle_bookmark(cb, MediaCallback(id="tt888", action="bookmark"), media_service, user)
    cb.answer.assert_called_with("⭐ Saved to bookmarks!")

    # Seasons view
    await handle_seasons_view(cb, MediaCallback(id="tt888", action="seasons"), media_service)
    cb.message.edit_text.assert_called()

    # Season episodes view
    await handle_season_episodes(cb, SeasonCallback(id="tt888", season=1), media_service)
    cb.message.edit_text.assert_called()

    # Episode streams view
    await handle_episode_streams(cb, EpisodeCallback(id="tt888", season=1, episode=1), media_service, user)
    cb.message.edit_text.assert_called()

    # Stream detail view
    await handle_stream_detail_view(cb, StreamCallback(id="tt888", season=1, episode=1, idx=0, action="view"), media_service, user)
    cb.message.edit_text.assert_called()


@pytest.mark.asyncio
async def test_downloads_handlers(tmp_path):
    storage = StorageManager(db_path=tmp_path / "test_handlers_dls.db")
    dl_service = DownloadService(storage=storage)
    user = UserRecord(user_id=3, username="u3")

    rec_id = storage.create_download(
        media_id="tt99",
        media_title="Sample Film",
        source_type=SourceType.HTTP,
        target_url="http://example.com/film.mp4",
        user_id=3,
    )

    # List downloads
    cb = MagicMock(spec=CallbackQuery)
    cb.message = AsyncMock()
    cb.answer = AsyncMock()
    await handle_list_downloads(cb, dl_service, user)
    cb.message.edit_text.assert_called()

    # View download
    await handle_view_download(cb, DownloadCallback(id=rec_id, action="view"), dl_service)
    cb.message.edit_text.assert_called()

    # Cancel download
    await handle_cancel_download(cb, DownloadCallback(id=rec_id, action="cancel"), dl_service)
    rec = storage.get_download(rec_id)
    assert rec.status == DownloadStatus.CANCELLED
