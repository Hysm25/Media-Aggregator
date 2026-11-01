"""Download actions, active progress tracking, cancel, and magnet export handlers."""

from __future__ import annotations

import asyncio
from aiogram import F, Router, types
from aiogram.filters import Command
from media_aggregator.bot.callbacks import DownloadCallback, NavCallback, StreamCallback
from media_aggregator.bot.keyboards import (
    download_control_keyboard,
    downloads_list_keyboard,
    main_menu_keyboard,
)
from media_aggregator.models import DownloadRecord, DownloadStatus, UserRecord
from media_aggregator.services.download_service import DownloadService
from media_aggregator.services.media_service import MediaService

router = Router(name="downloads")


def format_progress_bar(percent: float, length: int = 15) -> str:
    """Render a visual text-based progress bar."""
    filled = int(length * (percent / 100.0))
    filled = max(0, min(length, filled))
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent:.1f}%"


def format_bytes(bytes_count: int) -> str:
    """Format byte integers into human-readable size strings."""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} KB"
    elif bytes_count < 1024 * 1024 * 1024:
        return f"{bytes_count / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_count / (1024 * 1024 * 1024):.2f} GB"


def format_speed(bps: float) -> str:
    """Format speed in bytes/sec to human-readable string."""
    return f"{format_bytes(int(bps))}/s"


@router.callback_query(StreamCallback.filter(F.action == "dl"))
async def handle_start_download(
    callback: types.CallbackQuery,
    callback_data: StreamCallback,
    media_service: MediaService,
    download_service: DownloadService,
    user_record: UserRecord,
) -> None:
    """Initiate async download of selected stream."""
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
    item = await media_service.get_details(callback_data.id)
    title = item.title if item else callback_data.id
    if is_series:
        title = f"{title} S{callback_data.season:02d}E{callback_data.episode:02d}"

    status_msg = await callback.message.edit_text(  # type: ignore
        f"⏳ **Starting Download**\n\n"
        f"🎬 **Title**: `{title}`\n"
        f"⚙️ **Type**: {stream.source_type.value.upper()}\n"
        "Initializing download engine...",
        parse_mode="Markdown",
    )

    async def on_progress(record: DownloadRecord) -> None:
        try:
            bar = format_progress_bar(record.progress_percent)
            dl_str = format_bytes(record.downloaded_bytes)
            tot_str = format_bytes(record.total_bytes) if record.total_bytes > 0 else "N/A"
            spd_str = format_speed(record.speed_bps)
            eta_str = f"{record.eta_seconds}s" if record.eta_seconds else "calculating..."

            text = (
                f"⏳ **Downloading**: `{title}`\n\n"
                f"{bar}\n"
                f"💾 **Progress**: {dl_str} / {tot_str}\n"
                f"🚀 **Speed**: {spd_str} • ⏱️ **ETA**: {eta_str}"
            )
            await status_msg.edit_text(
                text,
                parse_mode="Markdown",
                reply_markup=download_control_keyboard(record.id or 0, is_active=True),
            )
        except Exception:
            pass

    async def on_completed(record: DownloadRecord) -> None:
        try:
            text = (
                f"✅ **Download Completed!**\n\n"
                f"🎬 **Title**: `{title}`\n"
                f"📁 **Local File**: `{record.local_path}`\n"
                f"💾 **Size**: {format_bytes(record.downloaded_bytes)}"
            )
            await status_msg.edit_text(
                text,
                parse_mode="Markdown",
                reply_markup=download_control_keyboard(record.id or 0, is_active=False),
            )
        except Exception:
            pass

    async def on_failed(record: DownloadRecord, err: str) -> None:
        try:
            text = (
                f"❌ **Download Failed**\n\n"
                f"🎬 **Title**: `{title}`\n"
                f"⚠️ **Error**: `{err}`"
            )
            await status_msg.edit_text(
                text,
                parse_mode="Markdown",
                reply_markup=download_control_keyboard(record.id or 0, is_active=False),
            )
        except Exception:
            pass

    rec = await download_service.start_download(
        stream=stream,
        media_id=callback_data.id,
        media_title=title,
        user_id=user_record.user_id,
        on_progress=on_progress,
        on_completed=on_completed,
        on_failed=on_failed,
    )

    if stream.is_torrent:
        await status_msg.edit_text(
            f"✅ **Torrent Source Processed!**\n\n"
            f"🎬 **Title**: `{title}`\n"
            f"📁 **Magnet File**: `{rec.local_path}`\n\n"
            f"💡 *The `.magnet` file was saved and dispatched to your local BitTorrent client.*",
            parse_mode="Markdown",
            reply_markup=download_control_keyboard(rec.id or 0, is_active=False),
        )


@router.callback_query(StreamCallback.filter(F.action == "magnet"))
async def handle_copy_magnet(
    callback: types.CallbackQuery,
    callback_data: StreamCallback,
    media_service: MediaService,
    user_record: UserRecord,
) -> None:
    """Provide clickable RFC Magnet URI."""
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
        await callback.answer("Stream not found.", show_alert=True)
        return

    stream = streams[callback_data.idx]
    magnet_uri = stream.build_magnet_uri()
    if not magnet_uri:
        await callback.answer("Could not build Magnet link.", show_alert=True)
        return

    await callback.message.answer(  # type: ignore
        f"🧲 **Magnet URI**\n\n"
        f"```\n{magnet_uri}\n```\n"
        "Tap the text above to copy it into your clipboard.",
        parse_mode="Markdown",
    )
    await callback.answer("Magnet link sent!")


@router.callback_query(NavCallback.filter(F.action == "downloads"))
@router.message(Command("downloads"))
async def handle_list_downloads(
    event: types.Message | types.CallbackQuery,
    download_service: DownloadService,
    user_record: UserRecord,
) -> None:
    """Display active downloads and recent history."""
    downloads = await download_service.get_download_history(user_id=user_record.user_id, limit=10)
    if not downloads:
        text = "📥 **Downloads**\n\nNo active or past downloads found."
        keyboard = main_menu_keyboard(is_admin=user_record.is_admin)
    else:
        text = (
            f"📥 **Downloads ({len(downloads)})**\n\n"
            "Select an item to view detailed status or controls:"
        )
        keyboard = downloads_list_keyboard(downloads)

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)  # type: ignore
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown", reply_markup=keyboard)


@router.callback_query(DownloadCallback.filter(F.action == "view"))
async def handle_view_download(
    callback: types.CallbackQuery,
    callback_data: DownloadCallback,
    download_service: DownloadService,
) -> None:
    """Display detailed progress and options for a specific download."""
    rec = await download_service.get_download(callback_data.id)
    if not rec:
        await callback.answer("Download record not found.", show_alert=True)
        return

    is_active = rec.status == DownloadStatus.DOWNLOADING
    bar = format_progress_bar(rec.progress_percent)
    dl_str = format_bytes(rec.downloaded_bytes)
    tot_str = format_bytes(rec.total_bytes) if rec.total_bytes > 0 else "N/A"

    lines = [
        f"📥 **Download Job #{rec.id}**\n",
        f"🎬 **Title**: `{rec.media_title}`",
        f"📊 **Status**: {rec.status.value.upper()}",
        f"⚙️ **Source**: {rec.source_type.value.upper()}",
        f"{bar}",
        f"💾 **Transferred**: {dl_str} / {tot_str}",
    ]
    if rec.local_path:
        lines.append(f"📁 **Path**: `{rec.local_path}`")
    if rec.error_message:
        lines.append(f"⚠️ **Message**: `{rec.error_message}`")

    text = "\n".join(lines)
    await callback.message.edit_text(  # type: ignore
        text,
        parse_mode="Markdown",
        reply_markup=download_control_keyboard(rec.id or 0, is_active=is_active),
    )
    await callback.answer()


@router.callback_query(DownloadCallback.filter(F.action == "cancel"))
async def handle_cancel_download(
    callback: types.CallbackQuery,
    callback_data: DownloadCallback,
    download_service: DownloadService,
) -> None:
    """Cancel an ongoing download."""
    await download_service.cancel_download(callback_data.id)
    await callback.answer("🚫 Download cancelled.")
    # Refresh view
    rec = await download_service.get_download(callback_data.id)
    if rec:
        await callback.message.edit_text(  # type: ignore
            f"🚫 **Download Cancelled**\n\n"
            f"🎬 **Title**: `{rec.media_title}`\n"
            f"Download was aborted by user.",
            parse_mode="Markdown",
            reply_markup=download_control_keyboard(rec.id or 0, is_active=False),
        )


@router.callback_query(DownloadCallback.filter(F.action == "refresh"))
async def handle_refresh_download(
    callback: types.CallbackQuery,
    callback_data: DownloadCallback,
    download_service: DownloadService,
) -> None:
    """Refresh single download view."""
    rec = await download_service.get_download(callback_data.id)
    if not rec:
        await callback.answer("Record not found.", show_alert=True)
        return

    is_active = rec.status == DownloadStatus.DOWNLOADING
    bar = format_progress_bar(rec.progress_percent)
    dl_str = format_bytes(rec.downloaded_bytes)
    tot_str = format_bytes(rec.total_bytes) if rec.total_bytes > 0 else "N/A"

    lines = [
        f"📥 **Download Job #{rec.id}**\n",
        f"🎬 **Title**: `{rec.media_title}`",
        f"📊 **Status**: {rec.status.value.upper()}",
        f"{bar}",
        f"💾 **Transferred**: {dl_str} / {tot_str}",
    ]
    if rec.speed_bps > 0:
        lines.append(f"🚀 **Speed**: {format_speed(rec.speed_bps)}")

    text = "\n".join(lines)
    await callback.message.edit_text(  # type: ignore
        text,
        parse_mode="Markdown",
        reply_markup=download_control_keyboard(rec.id or 0, is_active=is_active),
    )
    await callback.answer("Refreshed.")
