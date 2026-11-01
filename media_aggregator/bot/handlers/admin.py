"""Administrator dashboard and user authorization handlers."""

from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command
from media_aggregator.bot.callbacks import AdminCallback, NavCallback
from media_aggregator.bot.keyboards import admin_dashboard_keyboard, main_menu_keyboard
from media_aggregator.models import UserRecord
from media_aggregator.services.user_service import UserService

router = Router(name="admin")


@router.callback_query(NavCallback.filter(F.action == "admin"))
@router.message(Command("admin"))
async def handle_admin_dashboard(
    event: types.Message | types.CallbackQuery,
    user_record: UserRecord,
    user_service: UserService,
) -> None:
    """Display administrator overview and pending user authorizations."""
    if not user_record.is_admin:
        if isinstance(event, types.CallbackQuery):
            await event.answer("🚫 Administrator access required.", show_alert=True)
        else:
            await event.answer("🚫 Administrator access required.")
        return

    users = await user_service.list_users()
    pending = [u for u in users if not u.is_allowed and not u.is_admin]

    lines = [
        "👑 **Administrator Dashboard**\n",
        f"👥 **Total Registered Users**: {len(users)}",
        f"⏳ **Pending Approval**: {len(pending)}",
    ]
    if pending:
        lines.append("\nTap a user below to authorize access:")
    else:
        lines.append("\n*No pending user requests.*")

    text = "\n".join(lines)
    keyboard = admin_dashboard_keyboard(users)

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)  # type: ignore
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown", reply_markup=keyboard)


@router.callback_query(AdminCallback.filter(F.action == "approve"))
async def handle_approve_user(
    callback: types.CallbackQuery,
    callback_data: AdminCallback,
    user_record: UserRecord,
    user_service: UserService,
) -> None:
    """Authorize a pending user."""
    if not user_record.is_admin:
        await callback.answer("Admin permission required.", show_alert=True)
        return

    success = await user_service.approve_user(callback_data.uid)
    if success:
        await callback.answer("✅ User authorized!")
        # Try to send notification to approved user
        try:
            bot = callback.bot
            if bot:
                await bot.send_message(
                    chat_id=callback_data.uid,
                    text="🎉 **Access Approved!**\n\nYour account has been authorized by the administrator. Use /start to begin.",
                    parse_mode="Markdown",
                )
        except Exception:
            pass
    else:
        await callback.answer("Failed to authorize user.", show_alert=True)

    # Refresh dashboard
    users = await user_service.list_users()
    await callback.message.edit_text(  # type: ignore
        f"👑 **Administrator Dashboard**\n\nUser `{callback_data.uid}` has been authorized.",
        parse_mode="Markdown",
        reply_markup=admin_dashboard_keyboard(users),
    )


@router.callback_query(AdminCallback.filter(F.action == "stats"))
async def handle_system_stats(
    callback: types.CallbackQuery,
    user_record: UserRecord,
    user_service: UserService,
) -> None:
    """Display real-time system and database statistics."""
    if not user_record.is_admin:
        await callback.answer("Admin permission required.", show_alert=True)
        return

    stats = user_service.storage.get_system_stats()
    text = (
        "📊 **System & Database Metrics**\n\n"
        f"• 🎬 **Cached Media Items**: {stats.get('cached_media', 0)}\n"
        f"• ⚡ **Stream Records Tracked**: {stats.get('discovered_streams', 0)}\n"
        f"• 📥 **Total Downloads**: {stats.get('total_downloads', 0)}\n"
        f"• ⏳ **Active Downloads**: {stats.get('active_downloads', 0)}\n"
        f"• ✅ **Completed Downloads**: {stats.get('completed_downloads', 0)}\n"
        f"• 👥 **Registered Users**: {stats.get('total_users', 0)} ({stats.get('allowed_users', 0)} active)\n"
        f"• 🟢 **Enabled Add-ons**: {stats.get('active_addons', 0)}"
    )

    users = await user_service.list_users()
    await callback.message.edit_text(  # type: ignore
        text,
        parse_mode="Markdown",
        reply_markup=admin_dashboard_keyboard(users),
    )
    await callback.answer()
