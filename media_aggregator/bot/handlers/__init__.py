"""Telegram bot message and callback query handlers."""

from aiogram import Router
from media_aggregator.bot.handlers import addons, admin, downloads, media, search, settings, start


def register_handlers() -> Router:
    """Combine all handler sub-routers into a master bot router."""
    master = Router(name="master")
    master.include_router(start.router)
    master.include_router(search.router)
    master.include_router(media.router)
    master.include_router(downloads.router)
    master.include_router(settings.router)
    master.include_router(addons.router)
    master.include_router(admin.router)
    return master
