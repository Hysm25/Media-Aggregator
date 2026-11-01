"""Media details, season navigation, episode selection, and stream discovery handlers."""

from __future__ import annotations

import logging
import math
from typing import List
from aiogram import F, Router, types
from media_aggregator.bot.callbacks import (
    EpisodeCallback,
    MediaCallback,
    SeasonCallback,
    StreamCallback,
)
from media_aggregator.bot.keyboards import (
    episodes_keyboard,
    media_detail_keyboard,
    seasons_keyboard,
    stream_action_keyboard,
    streams_keyboard,
)
from media_aggregator.bot.ui_utils import (
    escape_markdown,
    format_media_caption,
    render_media_card,
    safe_edit_or_replace_message,
)
from media_aggregator.models import EpisodeItem, MediaType, UserRecord
from media_aggregator.services.media_service import MediaService

logger = logging.getLogger("media_aggregator.bot.media")
router = Router(name="media")


@router.callback_query(MediaCallback.filter(F.action == "view"))
async def handle_media_view(
    callback: types.CallbackQuery,
    callback_data: MediaCallback,
    media_service: MediaService,
    user_record: UserRecord,
) -> None:
    """Display synopsis and details for selected media item with poster image."""
    item = await media_service.get_details(callback_data.id)
    if not item:
        await callback.answer("Unable to load media details.", show_alert=True)
        return

    # Check bookmark status
    bookmarks = media_service.storage.get_bookmarks(user_id=user_record.user_id)
    is_bm = any(b.get("media_id") == item.id for b in bookmarks)

    caption = format_media_caption(item)
    keyboard = media_detail_keyboard(item, is_bookmarked=is_bm)

    if callback.message:
        await render_media_card(
            message=callback.message,
            item=item,
            caption=caption,
            reply_markup=keyboard,
        )
    await callback.answer()


@router.callback_query(MediaCallback.filter(F.action == "bookmark"))
async def handle_toggle_bookmark(
    callback: types.CallbackQuery,
    callback_data: MediaCallback,
    media_service: MediaService,
    user_record: UserRecord,
) -> None:
    """Add or remove item from personal bookmarks."""
    item = await media_service.get_details(callback_data.id)
    if not item:
        await callback.answer("Media item not found.", show_alert=True)
        return

    bookmarks = media_service.storage.get_bookmarks(user_id=user_record.user_id)
    is_bm = any(b.get("media_id") == item.id for b in bookmarks)

    if is_bm:
        media_service.storage.remove_bookmark(item.id, user_id=user_record.user_id)
        await callback.answer("🗑️ Removed from bookmarks.")
    else:
        media_service.storage.add_bookmark(item, user_id=user_record.user_id)
        await callback.answer("⭐ Saved to bookmarks!")

    # Refresh keyboard
    await callback.message.edit_reply_markup(  # type: ignore
        reply_markup=media_detail_keyboard(item, is_bookmarked=not is_bm),
    )


@router.callback_query(MediaCallback.filter(F.action == "backdrop"))
async def handle_media_backdrop(
    callback: types.CallbackQuery,
    callback_data: MediaCallback,
    media_service: MediaService,
    user_record: UserRecord,
) -> None:
    """Display landscape backdrop artwork for a media item without replacing the portrait poster."""
    item = await media_service.get_details(callback_data.id)
    if not item or not item.background:
        await callback.answer("Backdrop artwork not available.", show_alert=True)
        return

    safe_title = escape_markdown(item.title)
    caption = f"🖼️ *{safe_title}* — Official Artwork\n\nLandscape backdrop provided by Cinemeta."
    back_kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔙 Back to Media Details",
                    callback_data=MediaCallback(id=item.id, action="view").pack(),
                )
            ]
        ]
    )

    if callback.message:
        await render_media_card(
            message=callback.message,
            item=item,
            caption=caption,
            reply_markup=back_kb,
            image_url=item.background,
        )
    await callback.answer()


@router.callback_query(MediaCallback.filter(F.action == "seasons"))
async def handle_seasons_view(
    callback: types.CallbackQuery,
    callback_data: MediaCallback,
    media_service: MediaService,
) -> None:
    """Display available seasons for a TV series."""
    item = await media_service.get_details(callback_data.id)
    if not item or not item.episodes:
        await callback.answer("No seasons found for this series.", show_alert=True)
        return

    season_numbers = sorted(list({ep.season for ep in item.episodes if ep.season >= 0}))
    if not season_numbers:
        season_numbers = [1]

    safe_title = escape_markdown(item.title)
    if callback.message:
        await safe_edit_or_replace_message(
            message=callback.message,
            text=f"📺 **{safe_title}**\nSelect a season to view episodes:",
            reply_markup=seasons_keyboard(item.id, season_numbers),
        )
    await callback.answer()


@router.callback_query(SeasonCallback.filter())
async def handle_season_episodes(
    callback: types.CallbackQuery,
    callback_data: SeasonCallback,
    media_service: MediaService,
) -> None:
    """Display episode list for a chosen season."""
    item = await media_service.get_details(callback_data.id)
    if not item:
        await callback.answer("Series details not found.", show_alert=True)
        return

    episodes = [ep for ep in item.episodes if ep.season == callback_data.season]
    episodes.sort(key=lambda ep: ep.episode)

    if not episodes:
        await callback.answer("No episodes found for this season.", show_alert=True)
        return

    safe_title = escape_markdown(item.title)
    if callback.message:
        await safe_edit_or_replace_message(
            message=callback.message,
            text=f"📺 **{safe_title}** — Season {callback_data.season}\nSelect an episode:",
            reply_markup=episodes_keyboard(
                media_id=item.id,
                season=callback_data.season,
                episodes=episodes,
            ),
        )
    await callback.answer()


@router.callback_query(EpisodeCallback.filter())
async def handle_episode_streams(
    callback: types.CallbackQuery,
    callback_data: EpisodeCallback,
    media_service: MediaService,
    user_record: UserRecord,
) -> None:
    """Aggregate and present stream sources for a movie or TV episode with pagination."""
    item = await media_service.get_details(callback_data.id)
    raw_title = item.title if item else callback_data.id
    safe_title = escape_markdown(raw_title)

    is_series = (item and item.type == MediaType.SERIES) or callback_data.season > 0 or callback_data.episode > 0
    ep_str = f" S{callback_data.season:02d}E{callback_data.episode:02d}" if (callback_data.season > 0 or callback_data.episode > 0) else ""

    season_arg = callback_data.season if is_series else None
    episode_arg = callback_data.episode if is_series else None

    # Only show loading message on initial uncached query to prevent pagination flicker
    if callback_data.page == 0 and callback.message and not media_service.has_cached_streams(callback_data.id, season_arg, episode_arg):
        await safe_edit_or_replace_message(
            message=callback.message,
            text=f"⚡ Resolving streaming sources for **{safe_title}**{ep_str}...\nQuerying Torrentio and active providers...",
        )

    try:
        streams = await media_service.get_streams(
            media_id=callback_data.id,
            season=season_arg,
            episode=episode_arg,
            settings=user_record.settings,
        )
    except Exception as e:
        logger.error(f"Failed to aggregate streams for {callback_data.id}: {e}", exc_info=True)
        streams = []

    if not streams:
        if callback.message:
            await safe_edit_or_replace_message(
                message=callback.message,
                text=f"❌ No active stream sources found for **{safe_title}**{ep_str}.\nTry adjusting your settings or verifying active add-ons.",
                reply_markup=media_detail_keyboard(item, is_bookmarked=False) if item else None,
            )
        await callback.answer()
        return

    page_size = 5
    total_pages = max(1, math.ceil(len(streams) / page_size))
    curr_page = max(0, min(callback_data.page, total_pages - 1))
    slice_items = streams[curr_page * page_size : (curr_page + 1) * page_size]

    start_num = curr_page * page_size + 1
    end_num = min(len(streams), (curr_page + 1) * page_size)

    lines = [
        f"⚡ Found **{len(streams)}** stream sources for **{safe_title}**{ep_str}",
        f"📄 Page **{curr_page + 1}/{total_pages}** (Streams {start_num}–{end_num}):\n",
    ]
    for i, s in enumerate(slice_items):
        stream_num = curr_page * page_size + i + 1
        icon = "🧲" if s.is_torrent else "🌐"
        res = s.resolution or "HD"
        size = s.size_display or "Unknown"
        seeds = f" | 👤 {s.seeders}" if s.seeders is not None else ""
        rel_name = s.release_title or s.title or "Unknown Release"
        if len(rel_name) > 55:
            rel_name = rel_name[:52] + "..."
        prov = s.indexer or s.provider
        lines.append(f"**{stream_num}.** {icon} `[{res}]` {escape_markdown(rel_name)}")
        lines.append(f"     💾 {size}{seeds} • ⚙️ {escape_markdown(prov)}")

    lines.append("\nSelect a source to inspect details and obtain Magnet download links:")

    if callback.message:
        await safe_edit_or_replace_message(
            message=callback.message,
            text="\n".join(lines),
            reply_markup=streams_keyboard(
                media_id=callback_data.id,
                streams=streams,
                season=callback_data.season,
                episode=callback_data.episode,
                page=curr_page,
                page_size=page_size,
            ),
        )
    await callback.answer()


@router.callback_query(StreamCallback.filter(F.action == "view"))
async def handle_stream_detail_view(
    callback: types.CallbackQuery,
    callback_data: StreamCallback,
    media_service: MediaService,
    user_record: UserRecord,
) -> None:
    """Display rich metadata for a specific stream source."""
    is_series = callback_data.season > 0 or callback_data.episode > 0
    season_arg = callback_data.season if is_series else None
    episode_arg = callback_data.episode if is_series else None

    streams = await media_service.get_streams(
        media_id=callback_data.id,
        season=season_arg,
        episode=episode_arg,
        settings=user_record.settings,
    )

    if not streams or callback_data.idx >= len(streams):
        await callback.answer("Stream no longer available.", show_alert=True)
        return

    stream = streams[callback_data.idx]
    title = stream.release_title or stream.title or "Media Stream"
    safe_title = escape_markdown(title)

    if stream.is_torrent:
        source_type_str = "🧲 BitTorrent (Magnet Available)"
    elif stream.is_debrid:
        source_type_str = "⚡ Debrid Cloud Stream (Direct download disabled — Magnet only)"
    else:
        source_type_str = "🌐 Direct HTTP (Direct download disabled — Magnet only)"

    lines = [
        "⚡ **Stream Source Information**\n",
        f"📦 **Release**: `{safe_title}`",
        f"📡 **Source Type**: {source_type_str}",
        f"📊 **Resolution**: {stream.resolution}",
        f"💾 **Size**: {stream.size_display or 'Unknown'}",
        f"⚙️ **Provider**: {escape_markdown(stream.provider)}",
    ]
    if stream.seeders is not None:
        lines.append(f"👤 **Seeders**: {stream.seeders}")
    if stream.info_hash:
        lines.append(f"🔑 **InfoHash**: `{stream.info_hash}`")
    if stream.codecs:
        lines.append(f"🎞️ **Codecs**: {', '.join(stream.codecs)}")
    if stream.hdr:
        lines.append(f"✨ **HDR**: {', '.join(stream.hdr)}")
    if stream.audio:
        lines.append(f"🔊 **Audio**: {', '.join(stream.audio)}")
    if stream.indexer:
        lines.append(f"🏷️ **Indexer**: {escape_markdown(stream.indexer)}")

    caption = "\n".join(lines)
    keyboard = stream_action_keyboard(
        media_id=callback_data.id,
        stream=stream,
        season=callback_data.season,
        episode=callback_data.episode,
        stream_idx=callback_data.idx,
        page=callback_data.page,
    )

    if callback.message:
        await safe_edit_or_replace_message(
            message=callback.message,
            text=caption,
            reply_markup=keyboard,
        )
    await callback.answer()
