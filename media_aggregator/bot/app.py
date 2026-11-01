"""Bot application factory, dependency injection, and polling lifecycle manager."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Optional
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from media_aggregator.bot.config import BotConfig
from media_aggregator.bot.handlers import register_handlers
from media_aggregator.bot.middlewares.auth import AuthMiddleware
from media_aggregator.bot.middlewares.rate_limit import RateLimitMiddleware
from media_aggregator.services.addon_service import AddonService
from media_aggregator.services.download_service import DownloadService
from media_aggregator.services.media_service import MediaService
from media_aggregator.services.user_service import UserService
from media_aggregator.storage import StorageManager

logger = logging.getLogger("media_aggregator.bot")


def create_bot(token: str) -> Bot:
    """Instantiate aiogram Bot instance with default markdown properties."""
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )


def create_dispatcher(
    config: BotConfig,
    storage: Optional[StorageManager] = None,
) -> Dispatcher:
    """Create and configure Dispatcher with dependency injection and middlewares."""
    dp = Dispatcher()
    storage_mgr = storage or StorageManager(db_path=config.database_path)

    # Instantiate services
    media_service = MediaService(storage=storage_mgr)
    download_service = DownloadService(storage=storage_mgr, download_dir=config.download_dir)
    user_service = UserService(storage=storage_mgr)
    addon_service = AddonService(storage=storage_mgr)

    # Inject services into dispatcher workflow data
    dp["config"] = config
    dp["storage"] = storage_mgr
    dp["media_service"] = media_service
    dp["download_service"] = download_service
    dp["user_service"] = user_service
    dp["addon_service"] = addon_service

    # Setup middlewares
    auth_mw = AuthMiddleware(user_service=user_service, config=config)
    rate_mw = RateLimitMiddleware(rate_limit_seconds=config.rate_limit_seconds)

    dp.message.middleware(rate_mw)
    dp.message.middleware(auth_mw)
    dp.callback_query.middleware(rate_mw)
    dp.callback_query.middleware(auth_mw)

    # Register handlers
    master_router = register_handlers()
    dp.include_router(master_router)

    return dp


async def setup_bot_commands(bot: Bot) -> None:
    """Configure command menu in Telegram UI."""
    commands = [
        BotCommand(command="start", description="Open main navigation menu"),
        BotCommand(command="search", description="Search movies and series"),
        BotCommand(command="downloads", description="View active & past downloads"),
        BotCommand(command="settings", description="Adjust preferences & filters"),
        BotCommand(command="addons", description="Manage Stremio add-on sources"),
        BotCommand(command="help", description="Show usage guide & tips"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as e:
        logger.warning(f"Could not register Telegram bot commands: {e}")


async def run_bot(
    config: Optional[BotConfig] = None,
    storage: Optional[StorageManager] = None,
) -> None:
    """Run Telegram Bot polling with graceful shutdown handling."""
    cfg = config or BotConfig.from_env()
    cfg.validate(require_token=True)

    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    bot = create_bot(cfg.bot_token)
    dp = create_dispatcher(cfg, storage=storage)

    # Recover any interrupted downloads from previous sessions
    download_service: DownloadService = dp["download_service"]
    recovered = await download_service.recover_interrupted_downloads()
    if recovered > 0:
        logger.info(f"Recovered and reset {recovered} interrupted download tasks.")

    await setup_bot_commands(bot)
    logger.info("Media Aggregator Telegram Bot is starting polling...")

    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()
