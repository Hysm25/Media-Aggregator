"""UI utilities for media card formatting, Markdown escaping, and Telegram photo/text message rendering."""

from __future__ import annotations

import logging
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, Mock
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto, LinkPreviewOptions
from media_aggregator.images import is_valid_image_url
from media_aggregator.models import MediaItem, MediaType

logger = logging.getLogger("media_aggregator.bot.ui_utils")


def is_photo_message(message: Any) -> bool:
    """Safely check if a message is an actual Telegram photo message, ignoring unittest Mocks."""
    photo = getattr(message, "photo", None)
    if isinstance(photo, (Mock, MagicMock, AsyncMock)) or photo is None:
        return False
    return isinstance(photo, list) and len(photo) > 0


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram legacy Markdown."""
    if not text:
        return ""
    for ch in ("*", "_", "`", "[", "]"):
        text = text.replace(ch, f"\\{ch}")
    return text


def format_media_caption(
    item: MediaItem,
    header: Optional[str] = None,
    footer: Optional[str] = None,
    max_synopsis_len: int = 350,
) -> str:
    """Format a clean, rich Stremio-like media card caption under 1024 characters."""
    if not item:
        return ""

    icon = "🎬" if item.type == MediaType.MOVIE else ("⛩️" if item.type == MediaType.ANIME else "📺")
    safe_title = escape_markdown(item.title)
    year_str = f" ({item.display_year})" if item.year else ""
    type_name = "Movie" if item.type == MediaType.MOVIE else ("Anime" if item.type == MediaType.ANIME else "Series")

    rating_str = f"⭐ IMDb: {item.imdb_rating}/10" if item.imdb_rating else ""
    runtime_str = f"⏳ {item.runtime}" if item.runtime else ""
    meta_pills = [part for part in [f"🏷️ {type_name}", rating_str, runtime_str] if part]
    meta_row = " • ".join(meta_pills)

    genres_str = f"🎭 {escape_markdown(', '.join(item.genres[:3]))}" if item.genres else ""
    cast_str = f"👤 Cast: {escape_markdown(', '.join(item.cast[:3]))}" if item.cast else ""
    director_str = f"🎬 Director: {escape_markdown(item.director)}" if item.director else ""

    lines = []
    if header:
        lines.append(header)
    lines.append(f"{icon} *{safe_title}*{year_str}")
    if meta_row:
        lines.append(meta_row)
    if genres_str:
        lines.append(genres_str)
    if director_str:
        lines.append(director_str)
    elif cast_str:
        lines.append(cast_str)

    if item.synopsis:
        synopsis_clean = item.synopsis.strip().replace("\n", " ")
        if len(synopsis_clean) > max_synopsis_len:
            synopsis_clean = synopsis_clean[: max_synopsis_len - 3].rstrip() + "..."
        safe_synopsis = escape_markdown(synopsis_clean)
        lines.append(f"\n📝 *Synopsis*:\n{safe_synopsis}")

    if footer:
        lines.append(f"\n{footer}")

    full_text = "\n".join(lines)
    # Telegram photo captions have a hard limit of 1024 characters
    if len(full_text) > 1000:
        full_text = full_text[:997] + "..."

    return full_text


async def render_media_card(
    message: types.Message,
    item: Optional[MediaItem],
    caption: str,
    reply_markup: InlineKeyboardMarkup,
    image_url: Optional[str] = None,
) -> types.Message:
    """Render a visual media card with poster image, falling back gracefully to text on error.
    
    Uses Bot API 7.0 LinkPreviewOptions with prefer_large_media=True and show_above_text=True
    to deliver a Stremio-like visual poster at the top of the card without photo-conversion hurdles.
    """
    target_img: Optional[str] = None
    if image_url and is_valid_image_url(image_url):
        target_img = image_url
    elif item:
        if is_valid_image_url(item.poster):
            target_img = item.poster
        elif is_valid_image_url(item.background):
            target_img = item.background

    link_preview = None
    text_content = caption
    if target_img:
        text_content = f"[\u200b]({target_img}){caption}"
        link_preview = LinkPreviewOptions(
            url=target_img,
            prefer_large_media=True,
            show_above_text=True,
            is_disabled=False,
        )
    else:
        link_preview = LinkPreviewOptions(is_disabled=True)

    # 1. Handle real photo messages
    if is_photo_message(message):
        if target_img:
            try:
                await message.edit_media(
                    media=InputMediaPhoto(media=target_img, caption=caption, parse_mode="Markdown"),
                    reply_markup=reply_markup,
                )
                return message
            except Exception as e:
                logger.debug(f"edit_media photo update failed ({e}), falling back to edit_caption")
        try:
            await message.edit_caption(
                caption=caption[:1000],
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )
            return message
        except Exception:
            pass

    # 2. Standard edit_text with large media preview
    try:
        await message.edit_text(
            text_content,
            parse_mode="Markdown",
            reply_markup=reply_markup,
            link_preview_options=link_preview,
        )
        return message
    except Exception:
        # Fallback without markdown if markdown parsing failed
        plain_caption = caption.replace("*", "").replace("`", "").replace("_", "")
        plain_text = f"[\u200b]({target_img}){plain_caption}" if target_img else plain_caption
        await message.edit_text(
            plain_text,
            reply_markup=reply_markup,
            link_preview_options=link_preview,
        )
        return message


async def safe_edit_or_replace_message(
    message: types.Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = "Markdown",
) -> types.Message:
    """Safely edit message text or replace photo message with text message.
    
    Prevents 'there is no text in the message to edit' Telegram errors when transitioning
    from a media photo card to text-based menus (e.g. season or episode lists).
    """
    if is_photo_message(message):
        try:
            new_msg = await message.answer(
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            try:
                await message.delete()
            except Exception:
                pass
            return new_msg
        except Exception as e:
            logger.debug(f"Failed to replace photo with text message ({e}), attempting edit_caption")
            try:
                await message.edit_caption(
                    caption=text[:1000],
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
                return message
            except Exception:
                pass

    try:
        await message.edit_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return message
    except Exception:
        plain_text = text.replace("*", "").replace("`", "").replace("_", "")
        await message.edit_text(
            plain_text,
            reply_markup=reply_markup,
        )
        return message

