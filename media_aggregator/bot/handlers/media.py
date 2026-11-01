"""Media details, season navigation, episode selection, and stream discovery handlers."""

from __future__ import annotations

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
from media_aggregator.models import EpisodeItem, MediaType, UserRecord
from media_aggregator.services.media_service import MediaService

router = Router(name="media")


@router.callback_query(MediaCallback.filter(F.action == "view"))
async def handle_media_view(
    callback: types.CallbackQuery,
    callback_data: MediaCallback,
    media_service: MediaService,
    user_record: UserRecord,
) -> None:
    """Display synopsis and details for selected media item."""
    item = await media_service.get_details(callback_data.id)
    if not item:
        await callback.answer("Unable to load media details.", show_alert=True)
        return

    # Check bookmark status
    bookmarks = media_service.storage.get_bookmarks(user_id=user_record.user_id)
    is_bm = any(b.get("media_id") == item.id for b in bookmarks)

    icon = "🎬" if item.type == MediaType.MOVIE else "📺"
    year_str = f" ({item.year})" if item.year else ""
    rating_str = f"⭐ IMDb: {item.imdb_rating}/10" if item.imdb_rating else ""
    runtime_str = f"⏳ {item.runtime}" if item.runtime else ""
    genres_str = f"🎭 {', '.join(item.genres)}" if item.genres else ""
    cast_str = f"👤 Cast: {', '.join(item.cast[:4])}" if item.cast else ""
    director_str = f"🎬 Director: {item.director}" if item.director else ""

    meta_lines = [part for part in [rating_str, runtime_str] if part]
    meta_row = " • ".join(meta_lines)

    text_parts = [f"{icon} **{item.title}**{year_str}"]
    if meta_row:
        text_parts.append(meta_row)
    if genres_str:
        text_parts.append(genres_str)
    if director_str:
        text_parts.append(director_str)
    if cast_str:
        text_parts.append(cast_str)

    if item.synopsis:
        text_parts.append(f"\n📝 *Synopsis*:\n{item.synopsis[:600]}")

    caption = "\n".join(text_parts)
    keyboard = media_detail_keyboard(item, is_bookmarked=is_bm)

    await callback.message.edit_text(  # type: ignore
        caption,
        parse_mode="Markdown",
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

    await callback.message.edit_text(  # type: ignore
        f"📺 **{item.title}**\nSelect a season to view episodes:",
        parse_mode="Markdown",
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

    await callback.message.edit_text(  # type: ignore
        f"📺 **{item.title}** - Season {callback_data.season}\nSelect an episode to resolve streaming sources:",
        parse_mode="Markdown",
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
    """Aggregate and present stream sources for a movie or TV episode."""
    item = await media_service.get_details(callback_data.id)
    title = item.title if item else callback_data.id

    is_series = callback_data.season > 0
    ep_str = f" S{callback_data.season:02d}E{callback_data.episode:02d}" if is_series else ""

    await callback.message.edit_text(  # type: ignore
        f"⚡ Resolving streaming sources for **{title}**{ep_str}...\n"
        "Querying Torrentio and active providers...",
        parse_mode="Markdown",
    )

    season_arg = callback_data.season if is_series else None
    episode_arg = callback_data.episode if is_series else None

    streams = await media_service.get_streams(
        media_id=callback_data.id,
        season=season_arg,
        episode=episode_arg,
        settings=user_record.settings,
    )

    if not streams:
        await callback.message.edit_text(  # type: ignore
            f"❌ No active stream sources found for **{title}**{ep_str}.\n"
            "Try adjusting your settings or verifying active add-ons.",
            parse_mode="Markdown",
            reply_markup=media_detail_keyboard(item, is_bookmarked=False) if item else None,
        )
        return

    await callback.message.edit_text(  # type: ignore
        f"⚡ Found **{len(streams)}** stream sources for **{title}**{ep_str}:\n"
        "Select a source to inspect details or start downloading:",
        parse_mode="Markdown",
        reply_markup=streams_keyboard(
            media_id=callback_data.id,
            streams=streams,
            season=callback_data.season,
            episode=callback_data.episode,
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
    is_series = callback_data.season > 0
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

    lines = [
        "⚡ **Stream Source Information**\n",
        f"📦 **Release**: `{title}`",
        f"📊 **Resolution**: {stream.resolution}",
        f"💾 **Size**: {stream.size_display or 'Unknown'}",
        f"⚙️ **Provider**: {stream.provider}",
    ]
    if stream.seeders is not None:
        lines.append(f"👤 **Seeders**: {stream.seeders}")
    if stream.codecs:
        lines.append(f"🎞️ **Codecs**: {', '.join(stream.codecs)}")
    if stream.hdr:
        lines.append(f"✨ **HDR**: {', '.join(stream.hdr)}")
    if stream.audio:
        lines.append(f"🔊 **Audio**: {', '.join(stream.audio)}")
    if stream.indexer:
        lines.append(f"🏷️ **Indexer**: {stream.indexer}")

    caption = "\n".join(lines)
    keyboard = stream_action_keyboard(
        media_id=callback_data.id,
        stream=stream,
        season=callback_data.season,
        episode=callback_data.episode,
        stream_idx=callback_data.idx,
    )

    await callback.message.edit_text(caption, parse_mode="Markdown", reply_markup=keyboard)  # type: ignore
    await callback.answer()
