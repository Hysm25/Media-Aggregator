"""Start, help, and setup wizard handler."""

from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from media_aggregator.bot.callbacks import AdminCallback, NavCallback
from media_aggregator.bot.keyboards import first_time_setup_keyboard, main_menu_keyboard
from media_aggregator.models import UserRecord
from media_aggregator.services.user_service import UserService

router = Router(name="start")


@router.message(CommandStart())
async def handle_start(message: types.Message, user_record: UserRecord, is_setup_mode: bool = False) -> None:
    """Handle /start command with welcome greeting or setup wizard."""
    if is_setup_mode:
        await message.answer(
            "👋 **Welcome to Media Aggregator Bot!**\n\n"
            "This bot is currently uninitialized with no registered administrators.\n"
            "Click below to claim administrator privileges and finalize first-time setup.",
            parse_mode="Markdown",
            reply_markup=first_time_setup_keyboard(),
        )
        return

    is_admin = user_record.is_admin
    await message.answer(
        f"👋 **Welcome to Media Source Aggregator**, {user_record.full_name or 'friend'}!\n\n"
        "Search movies and TV shows, resolve multi-provider streaming sources, "
        "and manage high-speed downloads directly through Telegram.\n\n"
        "Select an option from the menu below:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(is_admin=is_admin),
    )


@router.callback_query(AdminCallback.filter(F.action == "claim"))
async def handle_claim_admin(
    callback: types.CallbackQuery,
    user_record: UserRecord,
    user_service: UserService,
) -> None:
    """Execute initial administrator claim in setup wizard."""
    success = await user_service.claim_first_admin(
        user_id=user_record.user_id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )
    if success:
        await callback.message.edit_text(  # type: ignore
            "🎉 **Administrator Rights Claimed!**\n\n"
            f"User ID `{user_record.user_id}` is now registered as the primary bot administrator.\n"
            "You have full access to search, downloads, add-on management, and user authorizations.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(is_admin=True),
        )
    else:
        await callback.answer("An administrator is already configured.", show_alert=True)


@router.callback_query(NavCallback.filter(F.action == "home"))
async def handle_nav_home(callback: types.CallbackQuery, user_record: UserRecord) -> None:
    """Return to main menu."""
    await callback.message.edit_text(  # type: ignore
        "🏠 **Main Menu**\n\nSelect an option below to proceed:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(is_admin=user_record.is_admin),
    )
    await callback.answer()


@router.callback_query(NavCallback.filter(F.action == "help"))
@router.message(Command("help"))
async def handle_help(event: types.Message | types.CallbackQuery, user_record: UserRecord) -> None:
    """Display comprehensive command and usage help."""
    help_text = (
        "📖 **Media Aggregator Bot Guide**\n\n"
        "• **Search**: Type any movie or TV series title directly or use `/search <title>`.\n"
        "• **Browse**: Navigate seasons, inspect episodes, and review cast/synopsis.\n"
        "• **Streams**: Aggregates from Torrentio, Cinemeta, and other Stremio add-ons.\n"
        "• **Downloads**: Download HTTP/Debrid streams with resume or export `.magnet` files.\n"
        "• **Settings**: Customize resolution (4K/1080p), min seeders, and CAM filtering.\n\n"
        "**Available Commands**:\n"
        "`/start` - Open main menu\n"
        "`/search <query>` - Search movies and series\n"
        "`/downloads` - View active and completed downloads\n"
        "`/settings` - Configure user preferences\n"
        "`/addons` - Manage Stremio add-on providers\n"
        "`/help` - Show this help reference"
    )
    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(  # type: ignore
            help_text,
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(is_admin=user_record.is_admin),
        )
        await event.answer()
    else:
        await event.answer(
            help_text,
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(is_admin=user_record.is_admin),
        )


@router.callback_query(NavCallback.filter(F.action == "noop"))
async def handle_noop(callback: types.CallbackQuery) -> None:
    """No-operation handler for informational page counters."""
    await callback.answer()
