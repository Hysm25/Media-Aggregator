"""Telegram Bot package for Media Source Aggregator using aiogram."""

from media_aggregator.bot.app import create_bot, create_dispatcher, run_bot
from media_aggregator.bot.config import BotConfig

__all__ = ["create_bot", "create_dispatcher", "run_bot", "BotConfig"]
