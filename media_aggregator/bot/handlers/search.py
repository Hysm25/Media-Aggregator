"""Media search and pagination handlers."""

from __future__ import annotations

import logging
from aiogram import F, Router, types
from aiogram.filters import Command
from media_aggregator.bot.callbacks import NavCallback, SearchCallback
from media_aggregator.bot.keyboards import main_menu_keyboard, search_results_keyboard
from media_aggregator.models import UserRecord
from media_aggregator.services.media_service import MediaService

logger = logging.getLogger("media_aggregator.bot.search")
router = Router(name="search")


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram legacy Markdown."""
    if not text:
        return ""
    for ch in ("*", "_", "`", "[", "]"):
        text = text.replace(ch, f"\\{ch}")
    return text


@router.callback_query(NavCallback.filter(F.action == "search"))
async def handle_search_prompt(callback: types.CallbackQuery) -> None:
    """Prompt user to type a search query."""
    await callback.message.edit_text(  # type: ignore
        "🔍 **Search Media**\n\n"
        "Send the title of any movie or TV series as a text message:\n"
        "*(e.g., 'Interstellar', 'Breaking Bad', 'Inception')*",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(Command("search"))
async def handle_search_command(
    message: types.Message,
    media_service: MediaService,
    user_record: UserRecord,
) -> None:
    """Handle /search <query> command."""
    query = ""
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            query = parts[1].strip()

    if not query:
        await message.answer("🔍 Please specify a title to search, e.g.: `/search Interstellar`", parse_mode="Markdown")
        return

    await perform_search(message, query, media_service, user_record)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_search(
    message: types.Message,
    media_service: MediaService,
    user_record: UserRecord,
) -> None:
    """Treat regular text messages as search queries."""
    if not message.text:
        return
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("Please enter at least 2 characters to search.")
        return

    await perform_search(message, query, media_service, user_record)


async def perform_search(
    message: types.Message,
    query: str,
    media_service: MediaService,
    user_record: UserRecord,
) -> None:
    """Execute media search and reply with paginated results."""
    safe_query = escape_markdown(query)
    status_msg = await message.answer(f"🔍 Searching for *'{safe_query}'*...", parse_mode="Markdown")

    try:
        results = await media_service.search(query)
    except Exception as e:
        logger.error(f"Search failed for query='{query}': {e}", exc_info=True)
        await status_msg.edit_text(
            f"⚠️ An error occurred while searching for *'{safe_query}'*.\n"
            f"Details: `{escape_markdown(str(e)[:100])}`\n\n"
            "Please try again or check provider configurations.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(is_admin=user_record.is_admin),
        )
        return

    if not results:
        await status_msg.edit_text(
            f"❌ No movies or TV series found matching *'{safe_query}'*.\n"
            "Try checking the spelling or searching by a different title.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(is_admin=user_record.is_admin),
        )
        return

    await status_msg.edit_text(
        f"🎯 Found **{len(results)}** matches for *'{safe_query}'*:\nSelect an item to view synopsis and streams:",
        parse_mode="Markdown",
        reply_markup=search_results_keyboard(results=results, query=query, page=0),
    )


@router.callback_query(SearchCallback.filter())
async def handle_search_page(
    callback: types.CallbackQuery,
    callback_data: SearchCallback,
    media_service: MediaService,
) -> None:
    """Handle search results page navigation."""
    safe_query = escape_markdown(callback_data.query)
    try:
        results = await media_service.search(callback_data.query)
    except Exception as e:
        logger.warning(f"Search pagination failed for query='{callback_data.query}': {e}")
        results = []

    if not results:
        await callback.answer("No results found.", show_alert=True)
        return

    await callback.message.edit_text(  # type: ignore
        f"🎯 Matches for *'{safe_query}'*:\nSelect an item to view synopsis and streams:",
        parse_mode="Markdown",
        reply_markup=search_results_keyboard(
            results=results,
            query=callback_data.query,
            page=callback_data.page,
        ),
    )
    await callback.answer()
