"""Anti-flood rate limiting middleware."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class RateLimitMiddleware(BaseMiddleware):
    """Enforces cooldown intervals between incoming interactions to protect Telegram API limits."""

    def __init__(self, rate_limit_seconds: float = 0.8):
        super().__init__()
        self.rate_limit_seconds = rate_limit_seconds
        self._last_event: Dict[int, float] = {}

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
        now = time.monotonic()
        last_time = self._last_event.get(uid, 0.0)

        if now - last_time < self.rate_limit_seconds:
            if isinstance(event, CallbackQuery):
                await event.answer("⏳ Please slow down.", show_alert=False)
            return None

        self._last_event[uid] = now
        return await handler(event, data)
