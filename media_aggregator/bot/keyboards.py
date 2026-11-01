"""Inline keyboard builders for Telegram interface."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
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
from media_aggregator.models import (
    AddonConfig,
    DownloadRecord,
    DownloadStatus,
    EpisodeItem,
    MediaItem,
    MediaType,
    StreamSource,
    UserRecord,
    UserSettings,
)


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Build root main menu keyboard."""
    buttons = [
        [
            InlineKeyboardButton(text="🔍 Search Media", callback_data=NavCallback(action="search").pack()),
            InlineKeyboardButton(text="📥 Downloads", callback_data=NavCallback(action="downloads").pack()),
        ],
        [
            InlineKeyboardButton(text="⚙️ Settings", callback_data=NavCallback(action="settings").pack()),
            InlineKeyboardButton(text="🧩 Add-ons", callback_data=NavCallback(action="addons").pack()),
        ],
    ]
    if is_admin:
        buttons.append([
            InlineKeyboardButton(text="👑 Admin Dashboard", callback_data=NavCallback(action="admin").pack()),
        ])
    buttons.append([
        InlineKeyboardButton(text="ℹ️ Help & Info", callback_data=NavCallback(action="help").pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def search_results_keyboard(
    results: List[MediaItem],
    query: str,
    page: int = 0,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    """Build paginated search results keyboard."""
    total_pages = max(1, math.ceil(len(results) / page_size))
    page = max(0, min(page, total_pages - 1))
    slice_items = results[page * page_size : (page + 1) * page_size]

    buttons: List[List[InlineKeyboardButton]] = []
    for item in slice_items:
        icon = "🎬" if item.type == MediaType.MOVIE else "📺"
        year_str = f" ({item.year})" if item.year else ""
        label = f"{icon} {item.title[:28]}{year_str}"
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=MediaCallback(id=item.id, action="view").pack(),
            )
        ])

    # Navigation row
    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Prev",
                callback_data=SearchCallback(query=query[:20], page=page - 1).pack(),
            )
        )
    nav_row.append(
        InlineKeyboardButton(
            text=f"📄 {page + 1}/{total_pages}",
            callback_data=NavCallback(action="noop").pack(),
        )
    )
    if page < total_pages - 1:
        nav_row.append(
            InlineKeyboardButton(
                text="Next ➡️",
                callback_data=SearchCallback(query=query[:20], page=page + 1).pack(),
            )
        )

    if len(nav_row) > 1 or total_pages > 1:
        buttons.append(nav_row)

    buttons.append([
        InlineKeyboardButton(text="🔍 New Search", callback_data=NavCallback(action="search").pack()),
        InlineKeyboardButton(text="🏠 Home", callback_data=NavCallback(action="home").pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def media_detail_keyboard(item: MediaItem, is_bookmarked: bool = False) -> InlineKeyboardMarkup:
    """Build media details action keyboard."""
    buttons = []
    if item.type == MediaType.SERIES:
        buttons.append([
            InlineKeyboardButton(
                text="📺 Browse Seasons & Episodes",
                callback_data=MediaCallback(id=item.id, action="seasons").pack(),
            )
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                text="⚡ Find Movie Streams",
                callback_data=EpisodeCallback(id=item.id, season=0, episode=0).pack(),
            )
        ])

    bm_text = "🗑️ Remove Bookmark" if is_bookmarked else "⭐ Bookmark"
    buttons.append([
        InlineKeyboardButton(
            text=bm_text,
            callback_data=MediaCallback(id=item.id, action="bookmark").pack(),
        )
    ])
    buttons.append([
        InlineKeyboardButton(text="🔍 Search", callback_data=NavCallback(action="search").pack()),
        InlineKeyboardButton(text="🏠 Home", callback_data=NavCallback(action="home").pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def seasons_keyboard(media_id: str, season_numbers: List[int]) -> InlineKeyboardMarkup:
    """Build grid of seasons for a TV series."""
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for s in season_numbers:
        row.append(
            InlineKeyboardButton(
                text=f"Season {s}",
                callback_data=SeasonCallback(id=media_id, season=s).pack(),
            )
        )
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(text="🔙 Back to Media", callback_data=MediaCallback(id=media_id, action="view").pack()),
        InlineKeyboardButton(text="🏠 Home", callback_data=NavCallback(action="home").pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def episodes_keyboard(
    media_id: str,
    season: int,
    episodes: List[EpisodeItem],
    page: int = 0,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    """Build episodes keyboard for a chosen season."""
    total_pages = max(1, math.ceil(len(episodes) / page_size))
    page = max(0, min(page, total_pages - 1))
    slice_items = episodes[page * page_size : (page + 1) * page_size]

    buttons: List[List[InlineKeyboardButton]] = []
    for ep in slice_items:
        title = ep.title if ep.title and ep.title != "Episode" else f"Episode {ep.episode}"
        label = f"E{ep.episode:02d}: {title[:28]}"
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=EpisodeCallback(id=media_id, season=season, episode=ep.episode).pack(),
            )
        ])

    # Pagination row
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️ Prev",
                    callback_data=SeasonCallback(id=media_id, season=season).pack(),
                )
            )
        nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data=NavCallback(action="noop").pack()))
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="Next ➡️",
                    callback_data=SeasonCallback(id=media_id, season=season).pack(),
                )
            )
        buttons.append(nav_row)

    buttons.append([
        InlineKeyboardButton(text="🔙 Seasons", callback_data=MediaCallback(id=media_id, action="seasons").pack()),
        InlineKeyboardButton(text="🏠 Home", callback_data=NavCallback(action="home").pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def streams_keyboard(
    media_id: str,
    streams: List[StreamSource],
    season: int = 0,
    episode: int = 0,
    page: int = 0,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    """Build list of available stream sources."""
    total_pages = max(1, math.ceil(len(streams) / page_size))
    page = max(0, min(page, total_pages - 1))
    slice_items = streams[page * page_size : (page + 1) * page_size]

    buttons: List[List[InlineKeyboardButton]] = []
    for i, s in enumerate(slice_items):
        idx = page * page_size + i
        res = s.resolution or "HD"
        size = s.size_display or "N/A"
        seeds = f"👤{s.seeders}" if s.seeders is not None else ""
        badge = f"[{res} | {size} {seeds} | {s.provider[:8]}]"
        buttons.append([
            InlineKeyboardButton(
                text=badge,
                callback_data=StreamCallback(
                    id=media_id,
                    season=season,
                    episode=episode,
                    idx=idx,
                    action="view",
                ).pack(),
            )
        ])

    back_cb = SeasonCallback(id=media_id, season=season).pack() if season > 0 else MediaCallback(id=media_id, action="view").pack()
    buttons.append([
        InlineKeyboardButton(text="🔙 Back", callback_data=back_cb),
        InlineKeyboardButton(text="🏠 Home", callback_data=NavCallback(action="home").pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def stream_action_keyboard(
    media_id: str,
    stream: StreamSource,
    season: int = 0,
    episode: int = 0,
    stream_idx: int = 0,
) -> InlineKeyboardMarkup:
    """Build action buttons for a single selected stream."""
    buttons = [
        [
            InlineKeyboardButton(
                text="⬇️ Start Download",
                callback_data=StreamCallback(
                    id=media_id,
                    season=season,
                    episode=episode,
                    idx=stream_idx,
                    action="dl",
                ).pack(),
            )
        ]
    ]

    if stream.is_torrent:
        buttons.append([
            InlineKeyboardButton(
                text="🧲 Copy Magnet Link",
                callback_data=StreamCallback(
                    id=media_id,
                    season=season,
                    episode=episode,
                    idx=stream_idx,
                    action="magnet",
                ).pack(),
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="🔙 Back to Streams",
            callback_data=EpisodeCallback(id=media_id, season=season, episode=episode).pack(),
        ),
        InlineKeyboardButton(text="🏠 Home", callback_data=NavCallback(action="home").pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def downloads_list_keyboard(downloads: List[DownloadRecord]) -> InlineKeyboardMarkup:
    """Build interactive active and historical downloads keyboard."""
    buttons: List[List[InlineKeyboardButton]] = []

    for d in downloads[:8]:
        status_icon = "⏳"
        if d.status == DownloadStatus.COMPLETED:
            status_icon = "✅"
        elif d.status == DownloadStatus.FAILED:
            status_icon = "❌"
        elif d.status == DownloadStatus.CANCELLED:
            status_icon = "🚫"

        pct = f" {d.progress_percent:.0f}%" if d.status == DownloadStatus.DOWNLOADING else ""
        label = f"{status_icon} {d.media_title[:24]}{pct}"
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=DownloadCallback(id=d.id or 0, action="view").pack(),
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="🔄 Refresh", callback_data=NavCallback(action="downloads").pack()),
        InlineKeyboardButton(text="🏠 Home", callback_data=NavCallback(action="home").pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def download_control_keyboard(download_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """Build control buttons for an individual download job."""
    buttons = []
    if is_active:
        buttons.append([
            InlineKeyboardButton(
                text="❌ Cancel Download",
                callback_data=DownloadCallback(id=download_id, action="cancel").pack(),
            ),
            InlineKeyboardButton(
                text="🔄 Refresh",
                callback_data=DownloadCallback(id=download_id, action="refresh").pack(),
            ),
        ])

    buttons.append([
        InlineKeyboardButton(text="📥 All Downloads", callback_data=NavCallback(action="downloads").pack()),
        InlineKeyboardButton(text="🏠 Home", callback_data=NavCallback(action="home").pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def settings_keyboard(settings: UserSettings) -> InlineKeyboardMarkup:
    """Build settings modification keyboard."""
    cam_status = "✅ Filtered" if settings.exclude_cam else "❌ Allowed"
    buttons = [
        [
            InlineKeyboardButton(
                text=f"Resolution: [{settings.preferred_quality}]",
                callback_data=SettingsCallback(action="cycle_quality", key="quality", val=settings.preferred_quality).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=f"CAM/SCR Releases: [{cam_status}]",
                callback_data=SettingsCallback(action="toggle_cam", key="cam", val="").pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text=f"Min Seeders: [{settings.min_seeders}]",
                callback_data=SettingsCallback(action="cycle_seeds", key="seeds", val=str(settings.min_seeders)).pack(),
            )
        ],
        [
            InlineKeyboardButton(text="🏠 Home", callback_data=NavCallback(action="home").pack()),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def addons_list_keyboard(addons: List[AddonConfig]) -> InlineKeyboardMarkup:
    """Build Stremio add-on manager keyboard."""
    buttons: List[List[InlineKeyboardButton]] = []

    for a in addons:
        status_icon = "🟢" if a.enabled else "🔴"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status_icon} {a.name[:28]}",
                callback_data=AddonCallback(action="toggle", id=a.id).pack(),
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="➕ Add Manifest URL", callback_data=AddonCallback(action="add_prompt", id="").pack()),
        InlineKeyboardButton(text="🏠 Home", callback_data=NavCallback(action="home").pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_dashboard_keyboard(users: List[UserRecord]) -> InlineKeyboardMarkup:
    """Build administrator control panel keyboard."""
    buttons: List[List[InlineKeyboardButton]] = []

    # Display pending authorization requests
    pending = [u for u in users if not u.is_allowed and not u.is_admin]
    for u in pending[:4]:
        name = u.username or f"User {u.user_id}"
        buttons.append([
            InlineKeyboardButton(
                text=f"✅ Approve @{name}",
                callback_data=AdminCallback(action="approve", uid=u.user_id).pack(),
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="📊 System Statistics", callback_data=AdminCallback(action="stats", uid=0).pack()),
        InlineKeyboardButton(text="🏠 Home", callback_data=NavCallback(action="home").pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def first_time_setup_keyboard() -> InlineKeyboardMarkup:
    """Build setup wizard keyboard for claiming initial admin rights."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👑 Claim Administrator Access",
                    callback_data=AdminCallback(action="claim", uid=0).pack(),
                )
            ]
        ]
    )
