"""Authorization and personal bot protection middleware."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from media_aggregator.bot.callbacks import AdminCallback
from media_aggregator.bot.config import BotConfig
from media_aggregator.services.user_service import UserService


class AuthMiddleware(BaseMiddleware):
    """Restricts bot access to authorized users and guides first-time administrator setup."""

    def __init__(self, user_service: UserService, config: BotConfig):
        super().__init__()
        self.user_service = user_service
        self.config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        telegram_user = data.get("event_from_user")
        if not telegram_user:
            return await handler(event, data)

        uid = telegram_user.id
        username = telegram_user.username
        full_name = telegram_user.full_name

        # Ensure user record exists
        user = await self.user_service.get_or_create_user(
            user_id=uid,
            username=username,
            full_name=full_name,
        )

        # Check if user ID is in static configured admin IDs
        if uid in self.config.admin_ids and not user.is_admin:
            await self.user_service.make_admin(uid, username, full_name)
            user = await self.user_service.get_user(uid) or user

        # Check if bot has zero administrators (First-Time Setup Mode)
        has_admins = await self.user_service.has_admins()
        if not has_admins:
            # Allow event through to trigger first-time setup wizard
            data["user_record"] = user
            data["is_setup_mode"] = True
            return await handler(event, data)

        # Authorized check
        if user.is_allowed or user.is_admin:
            data["user_record"] = user
            data["is_setup_mode"] = False
            return await handler(event, data)

        # Unauthorized access handling
        if isinstance(event, Message):
            if event.text and event.text.startswith("/start"):
                await event.answer(
                    "🔒 **Access Restricted**\n\n"
                    "This Media Aggregator bot is operating in personal mode.\n"
                    f"Your Telegram ID: `{uid}`\n\n"
                    "Your access request has been logged and is pending administrator authorization.",
                    parse_mode="Markdown",
                )
            else:
                await event.answer("🚫 You are not authorized to use this bot.")
            return None

        elif isinstance(event, CallbackQuery):
            await event.answer("🚫 Access denied. Contact the bot administrator.", show_alert=True)
            return None

        return None
