"""Stremio add-on manager handlers."""

from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command
from media_aggregator.bot.callbacks import AddonCallback, NavCallback
from media_aggregator.bot.keyboards import addons_list_keyboard
from media_aggregator.models import UserRecord
from media_aggregator.services.addon_service import AddonService

router = Router(name="addons")


@router.callback_query(NavCallback.filter(F.action == "addons"))
@router.message(Command("addons"))
async def handle_addons_view(
    event: types.Message | types.CallbackQuery,
    addon_service: AddonService,
) -> None:
    """Display list of registered Stremio add-ons."""
    addons = await addon_service.list_addons()
    text = (
        "🧩 **Stremio Add-on Manager**\n\n"
        "Active add-ons provide streaming links and metadata catalogs.\n"
        "Tap any provider to toggle it on or off:\n"
        "*(🟢 Enabled | 🔴 Disabled)*"
    )
    keyboard = addons_list_keyboard(addons)
    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)  # type: ignore
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown", reply_markup=keyboard)


@router.callback_query(AddonCallback.filter(F.action == "toggle"))
async def handle_toggle_addon(
    callback: types.CallbackQuery,
    callback_data: AddonCallback,
    addon_service: AddonService,
    user_record: UserRecord,
) -> None:
    """Toggle an add-on on or off."""
    if not user_record.is_admin:
        await callback.answer("🚫 Administrator privileges required.", show_alert=True)
        return

    addons = await addon_service.list_addons()
    target = next((a for a in addons if a.id == callback_data.id), None)
    if not target:
        await callback.answer("Add-on not found.", show_alert=True)
        return

    new_state = not target.enabled
    await addon_service.toggle_addon(target.id, new_state)

    updated_addons = await addon_service.list_addons()
    await callback.message.edit_reply_markup(reply_markup=addons_list_keyboard(updated_addons))  # type: ignore
    state_str = "enabled" if new_state else "disabled"
    await callback.answer(f"'{target.name}' {state_str}.")


@router.callback_query(AddonCallback.filter(F.action == "add_prompt"))
async def handle_add_prompt(callback: types.CallbackQuery, user_record: UserRecord) -> None:
    """Explain how to add a manifest URL."""
    if not user_record.is_admin:
        await callback.answer("🚫 Administrator privileges required.", show_alert=True)
        return

    await callback.message.answer(  # type: ignore
        "➕ **Install New Add-on**\n\n"
        "To register a new Stremio add-on, send the command:\n"
        "`/add_addon <manifest_url>`\n\n"
        "Example:\n"
        "`/add_addon https://mediafusion.elfhosted.com/manifest.json`",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(Command("add_addon"))
async def handle_add_addon_command(
    message: types.Message,
    addon_service: AddonService,
    user_record: UserRecord,
) -> None:
    """Install a new Stremio add-on from manifest URL."""
    if not user_record.is_admin:
        await message.answer("🚫 Only administrators can install new add-ons.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: `/add_addon <manifest_url>`", parse_mode="Markdown")
        return

    url = parts[1].strip()
    status_msg = await message.answer(f"⏳ Probing manifest: `{url}`...", parse_mode="Markdown")

    success, msg, addon = await addon_service.add_addon_from_manifest_url(url)
    if success and addon:
        await status_msg.edit_text(
            f"✅ **Add-on Installed Successfully!**\n\n"
            f"**Name**: {addon.name}\n"
            f"**ID**: `{addon.id}`\n"
            f"**Base URL**: `{addon.base_url}`",
            parse_mode="Markdown",
        )
    else:
        await status_msg.edit_text(f"❌ **Installation Failed**\n\n{msg}", parse_mode="Markdown")
