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
from media_aggregator.bot.ui_utils import escape_markdown
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
    user_record: UserRecord,
    **kwargs,
) -> None:
    """Handle legacy download triggers by enforcing Magnet-only downloads."""
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
    if not stream.is_torrent:
        await callback.answer(
            "Direct HTTP file downloads are disabled in Telegram. Only Magnet downloads for external torrent clients are supported.",
            show_alert=True,
        )
        return

    magnet_uri = stream.build_magnet_uri()
    if not magnet_uri:
        await callback.answer("Could not build Magnet link.", show_alert=True)
        return

    item = await media_service.get_details(callback_data.id)
    title = item.title if item else callback_data.id
    if is_series:
        title = f"{title} S{callback_data.season:02d}E{callback_data.episode:02d}"

    if callback.message:
        await callback.message.answer(
            f"🧲 **BitTorrent Magnet URI**\n\n"
            f"🎬 **Release**: `{escape_markdown(title)}`\n"
            f"📊 **Resolution**: {stream.resolution} • 💾 **Size**: {stream.size_display or 'Unknown'}\n\n"
            f"```\n{magnet_uri}\n```\n"
            "Direct in-bot file downloads are disabled. Tap above to copy the Magnet link into your BitTorrent client.",
            parse_mode="Markdown",
        )
    await callback.answer("Magnet link delivered!")


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
    if not stream.is_torrent:
        await callback.answer("This stream is Direct HTTP, not a torrent source.", show_alert=True)
        return

    magnet_uri = stream.build_magnet_uri()
    if not magnet_uri:
        await callback.answer("Could not build Magnet link.", show_alert=True)
        return

    item = await media_service.get_details(callback_data.id)
    title = item.title if item else callback_data.id
    if is_series:
        title = f"{title} S{callback_data.season:02d}E{callback_data.episode:02d}"

    if callback.message:
        await callback.message.answer(
            f"🧲 **BitTorrent Magnet URI**\n\n"
            f"🎬 **Release**: `{escape_markdown(title)}`\n"
            f"📊 **Resolution**: {stream.resolution} • 💾 **Size**: {stream.size_display or 'Unknown'}\n\n"
            f"```\n{magnet_uri}\n```\n"
            "Tap the text above to copy it into your BitTorrent client (e.g. qBittorrent, Transmission, Flud).",
            parse_mode="Markdown",
        )
    await callback.answer("🧲 Magnet URI generated!")


@router.callback_query(StreamCallback.filter(F.action == "magnet_file"))
async def handle_send_magnet_file(
    callback: types.CallbackQuery,
    callback_data: StreamCallback,
    media_service: MediaService,
    user_record: UserRecord,
) -> None:
    """Generate and deliver a .magnet file for opening directly with an external torrent client."""
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
    if not stream.is_torrent:
        await callback.answer("This stream is Direct HTTP, not a torrent source.", show_alert=True)
        return

    magnet_uri = stream.build_magnet_uri()
    if not magnet_uri:
        await callback.answer("Could not build Magnet link.", show_alert=True)
        return

    item = await media_service.get_details(callback_data.id)
    base_title = item.title if item else callback_data.id
    if is_series:
        base_title = f"{base_title}_S{callback_data.season:02d}E{callback_data.episode:02d}"

    clean_filename = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in base_title)

    doc = types.BufferedInputFile(
        magnet_uri.encode("utf-8"),
        filename=f"{clean_filename}.magnet",
    )
    if callback.message:
        await callback.message.answer_document(
            document=doc,
            caption=(
                f"📁 **BitTorrent Magnet File**: `{clean_filename}.magnet`\n\n"
                f"📊 **Resolution**: {stream.resolution} • 💾 **Size**: {stream.size_display or 'Unknown'}\n"
                "Open this file with your BitTorrent client (e.g. qBittorrent, Transmission, LibreTorrent, Flud)."
            ),
            parse_mode="Markdown",
        )
    await callback.answer("📁 .magnet file sent!")


@router.callback_query(NavCallback.filter(F.action == "downloads"))
@router.message(Command("downloads"))
async def handle_list_downloads(
    event: types.Message | types.CallbackQuery,
    *args,
    user_record: Optional[UserRecord] = None,
    **kwargs,
) -> None:
    """Display information about Magnet-only downloads in Telegram."""
    user = user_record
    for a in args:
        if isinstance(a, UserRecord):
            user = a
    is_admin = user.is_admin if user else False
    text = (
        "📥 **Downloads in Telegram — Magnet Only**\n\n"
        "Direct media file downloading on the server has been disabled in Telegram.\n\n"
        "**How to Download Media**:\n"
        "1. Search for any movie or TV series using `/search <title>`\n"
        "2. Select a title and browse seasons/episodes\n"
        "3. Choose your preferred stream source\n"
        "4. Tap **🧲 Get Magnet URI** to copy the magnet link\n"
        "   or **📁 Send .magnet File** to download the file directly\n"
        "5. Open it with your external BitTorrent client (e.g. qBittorrent, Transmission, Flud)\n\n"
        "💡 *Direct HTTP streams are distinguished from Magnet streams and cannot be downloaded directly in Telegram.*"
    )
    keyboard = main_menu_keyboard(is_admin=is_admin)
    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)  # type: ignore
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown", reply_markup=keyboard)


@router.callback_query(DownloadCallback.filter(F.action == "view"))
async def handle_view_download(
    callback: types.CallbackQuery,
    callback_data: DownloadCallback,
    download_service: Optional[DownloadService] = None,
    *args,
    **kwargs,
) -> None:
    """Display download record details (legacy view)."""
    rec = await download_service.get_download(callback_data.id) if download_service else None
    if not rec:
        await callback.answer("Direct file downloading is disabled in Telegram. Use Magnet links.", show_alert=True)
        return
    if callback.message:
        await callback.message.edit_text(  # type: ignore
            f"📥 **Download Job #{rec.id}**\n\n"
            f"🎬 **Title**: `{rec.media_title}`\n"
            f"📊 **Status**: {rec.status.value.upper()}\n\n"
            "💡 *Direct downloads are disabled in Telegram. Use Magnet links.*",
            parse_mode="Markdown",
            reply_markup=download_control_keyboard(rec.id or 0, is_active=False),
        )
    await callback.answer()


@router.callback_query(DownloadCallback.filter(F.action == "cancel"))
async def handle_cancel_download(
    callback: types.CallbackQuery,
    callback_data: DownloadCallback,
    download_service: Optional[DownloadService] = None,
    *args,
    **kwargs,
) -> None:
    """Cancel legacy download job."""
    if download_service:
        await download_service.cancel_download(callback_data.id)
    await callback.answer("🚫 Download cancelled.")
    if callback.message:
        await callback.message.edit_text(  # type: ignore
            "🚫 **Download Cancelled**\n\nDirect file downloads are disabled in Telegram.",
            parse_mode="Markdown",
            reply_markup=download_control_keyboard(callback_data.id, is_active=False),
        )


@router.callback_query(DownloadCallback.filter(F.action == "refresh"))
async def handle_refresh_download(
    callback: types.CallbackQuery,
    callback_data: DownloadCallback,
    download_service: Optional[DownloadService] = None,
    *args,
    **kwargs,
) -> None:
    """Refresh legacy download job view."""
    await callback.answer("Direct file downloads are disabled in Telegram. Use Magnet links.", show_alert=True)


@router.callback_query(DownloadCallback.filter())
async def handle_legacy_download_callback(callback: types.CallbackQuery, **kwargs) -> None:
    """Inform user that direct background download management is disabled in Telegram."""
    await callback.answer(
        "Direct file downloading is disabled in Telegram. Use Magnet links for your torrent client.",
        show_alert=True,
    )
