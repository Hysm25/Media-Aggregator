"""User preference configuration handlers."""

from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command
from media_aggregator.bot.callbacks import NavCallback, SettingsCallback
from media_aggregator.bot.keyboards import settings_keyboard
from media_aggregator.models import UserRecord
from media_aggregator.services.user_service import UserService

router = Router(name="settings")


@router.callback_query(NavCallback.filter(F.action == "settings"))
@router.message(Command("settings"))
async def handle_settings_view(
    event: types.Message | types.CallbackQuery,
    user_record: UserRecord,
) -> None:
    """Display user configuration menu."""
    s = user_record.settings
    text = (
        "⚙️ **Application Settings**\n\n"
        "Customize stream resolution preferences, seed thresholds, and release filters.\n"
        "Click the options below to cycle through settings:"
    )
    keyboard = settings_keyboard(s)
    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)  # type: ignore
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown", reply_markup=keyboard)


@router.callback_query(SettingsCallback.filter(F.action == "cycle_quality"))
async def handle_cycle_quality(
    callback: types.CallbackQuery,
    user_record: UserRecord,
    user_service: UserService,
) -> None:
    """Cycle preferred video resolution."""
    qualities = ["1080p", "4K", "720p", "480p"]
    curr = user_record.settings.preferred_quality
    idx = (qualities.index(curr) + 1) % len(qualities) if curr in qualities else 0
    user_record.settings.preferred_quality = qualities[idx]

    await user_service.update_settings(user_record.user_id, user_record.settings)
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(user_record.settings))  # type: ignore
    await callback.answer(f"Resolution set to {qualities[idx]}")


@router.callback_query(SettingsCallback.filter(F.action == "toggle_cam"))
async def handle_toggle_cam(
    callback: types.CallbackQuery,
    user_record: UserRecord,
    user_service: UserService,
) -> None:
    """Toggle CAM / Screener exclusion filter."""
    user_record.settings.exclude_cam = not user_record.settings.exclude_cam
    await user_service.update_settings(user_record.user_id, user_record.settings)

    status = "Filtered" if user_record.settings.exclude_cam else "Allowed"
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(user_record.settings))  # type: ignore
    await callback.answer(f"CAM releases: {status}")


@router.callback_query(SettingsCallback.filter(F.action == "cycle_seeds"))
async def handle_cycle_seeds(
    callback: types.CallbackQuery,
    user_record: UserRecord,
    user_service: UserService,
) -> None:
    """Cycle minimum required seeders threshold."""
    seeds_options = [1, 5, 10, 25, 0]
    curr = user_record.settings.min_seeders
    idx = (seeds_options.index(curr) + 1) % len(seeds_options) if curr in seeds_options else 0
    user_record.settings.min_seeders = seeds_options[idx]

    await user_service.update_settings(user_record.user_id, user_record.settings)
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(user_record.settings))  # type: ignore
    await callback.answer(f"Min seeders: {seeds_options[idx]}")
