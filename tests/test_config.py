"""Tests for .env configuration loading, validation rules, and trusted admin authorization."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from aiogram.types import CallbackQuery, Message, User
from media_aggregator.bot.callbacks import AdminCallback
from media_aggregator.bot.config import BotConfig, ConfigValidationError
from media_aggregator.bot.handlers.start import handle_claim_admin, handle_start
from media_aggregator.bot.middlewares.auth import AuthMiddleware
from media_aggregator.downloader.http import HTTPDownloader
from media_aggregator.downloader.manager import DEFAULT_DOWNLOAD_DIR, DownloadManager
from media_aggregator.models import UserRecord
from media_aggregator.services.user_service import UserService
from media_aggregator.storage import DEFAULT_DB_PATH, StorageManager


def test_config_defaults():
    """Verify default configuration attributes and path expansion."""
    cfg = BotConfig()
    assert cfg.bot_token == ""
    assert cfg.admin_ids == []
    assert cfg.bot_mode == "personal"
    assert cfg.database_path == DEFAULT_DB_PATH.expanduser()
    assert cfg.download_dir == DEFAULT_DOWNLOAD_DIR.expanduser()
    assert cfg.rate_limit_seconds == 0.8
    assert cfg.max_concurrent_downloads == 3
    assert cfg.default_max_size_gb == 15.0
    assert cfg.download_chunk_size_kb == 1024
    assert cfg.log_level == "INFO"
    assert cfg.default_torrentio_url == "https://torrentio.strem.fun"
    assert cfg.default_cinemeta_url == "https://v3-cinemeta.strem.io"
    assert cfg.default_realdebrid_api_key is None
    assert cfg.default_alldebrid_api_key is None


def test_config_from_dotenv_file(tmp_path, monkeypatch):
    """Verify loading full configuration from a custom .env file."""
    # Clear any conflicting environment variables for this test
    for var in [
        "BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_IDS", "BOT_MODE",
        "DATABASE_PATH", "RATE_LIMIT_SECONDS", "DOWNLOAD_DIR", "MAX_CONCURRENT_DOWNLOADS",
        "DEFAULT_MAX_SIZE_GB", "DOWNLOAD_CHUNK_SIZE_KB", "LOG_LEVEL",
        "DEFAULT_TORRENTIO_URL", "DEFAULT_CINEMETA_URL",
        "DEFAULT_REALDEBRID_API_KEY", "DEFAULT_ALLDEBRID_API_KEY"
    ]:
        monkeypatch.delenv(var, raising=False)

    env_content = (
        "BOT_TOKEN=987654321:AAHjKLmnOPQRstuvWXyz1234567890abcdef\n"
        "TELEGRAM_ADMIN_IDS=111,222,333\n"
        "BOT_MODE=multi-user\n"
        f"DATABASE_PATH={tmp_path / 'custom_data.db'}\n"
        "RATE_LIMIT_SECONDS=1.5\n"
        f"DOWNLOAD_DIR={tmp_path / 'custom_downloads'}\n"
        "MAX_CONCURRENT_DOWNLOADS=5\n"
        "DEFAULT_MAX_SIZE_GB=25.5\n"
        "DOWNLOAD_CHUNK_SIZE_KB=2048\n"
        "LOG_LEVEL=DEBUG\n"
        "DEFAULT_TORRENTIO_URL=https://custom-torrentio.example.com\n"
        "DEFAULT_CINEMETA_URL=https://custom-cinemeta.example.com\n"
        "DEFAULT_REALDEBRID_API_KEY=test_rd_key_abc\n"
        "DEFAULT_ALLDEBRID_API_KEY=test_ad_key_xyz\n"
    )
    env_file = tmp_path / ".env.test"
    env_file.write_text(env_content)

    cfg = BotConfig.from_env(dotenv_path=env_file)

    assert cfg.bot_token == "987654321:AAHjKLmnOPQRstuvWXyz1234567890abcdef"
    assert cfg.admin_ids == [111, 222, 333]
    assert cfg.bot_mode == "multi-user"
    assert cfg.database_path == (tmp_path / "custom_data.db").resolve()
    assert cfg.rate_limit_seconds == 1.5
    assert cfg.download_dir == (tmp_path / "custom_downloads").resolve()
    assert cfg.max_concurrent_downloads == 5
    assert cfg.default_max_size_gb == 25.5
    assert cfg.download_chunk_size_kb == 2048
    assert cfg.log_level == "DEBUG"
    assert cfg.default_torrentio_url == "https://custom-torrentio.example.com"
    assert cfg.default_cinemeta_url == "https://custom-cinemeta.example.com"
    assert cfg.default_realdebrid_api_key == "test_rd_key_abc"
    assert cfg.default_alldebrid_api_key == "test_ad_key_xyz"

    # Must pass validation
    cfg.validate(require_token=True)


def test_config_cli_overrides(tmp_path):
    """Verify that explicit CLI arguments take precedence over defaults and env."""
    cfg = BotConfig.from_env(
        token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ12345",
        admin_id=888,
        download_dir=tmp_path / "cli_downloads",
        database_path=tmp_path / "cli_db.sqlite",
        bot_mode="multi-user",
    )
    assert cfg.bot_token == "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ12345"
    assert 888 in cfg.admin_ids
    assert cfg.download_dir == (tmp_path / "cli_downloads").resolve()
    assert cfg.database_path == (tmp_path / "cli_db.sqlite").resolve()
    assert cfg.bot_mode == "multi-user"
    cfg.validate()


def test_config_validation_missing_token():
    """Verify error when BOT_TOKEN is missing or blank."""
    cfg = BotConfig(bot_token="")
    with pytest.raises(ConfigValidationError) as exc:
        cfg.validate(require_token=True)
    assert "BOT_TOKEN is required" in str(exc.value)


def test_config_validation_invalid_token_format():
    """Verify error on invalid Telegram token formats."""
    bad_tokens = ["not_a_valid_token", "12345", "abc:short", "no_colon_at_all_here_1234567890"]
    for bad in bad_tokens:
        cfg = BotConfig(bot_token=bad)
        with pytest.raises(ConfigValidationError) as exc:
            cfg.validate(require_token=True)
        assert "Invalid BOT_TOKEN format" in str(exc.value)


def test_config_validation_invalid_bot_mode():
    """Verify error when BOT_MODE is neither 'personal' nor 'multi-user'."""
    cfg = BotConfig(bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ12345", bot_mode="public-open")
    with pytest.raises(ConfigValidationError) as exc:
        cfg.validate()
    assert "Invalid BOT_MODE" in str(exc.value)


def test_config_validation_invalid_admin_ids(monkeypatch):
    """Verify error when non-numeric or negative admin IDs are passed."""
    # Test non-numeric string in environment variable
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123,abc,456")
    with pytest.raises(ConfigValidationError) as exc:
        BotConfig.from_env()
    assert "Invalid TELEGRAM_ADMIN_IDS" in str(exc.value)

    # Test negative ID
    cfg = BotConfig(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ12345",
        admin_ids=[-99],
    )
    with pytest.raises(ConfigValidationError) as exc:
        cfg.validate()
    assert "positive integers" in str(exc.value)


def test_config_validation_invalid_numeric_limits():
    """Verify error when numbers are outside permissible ranges."""
    valid_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ12345"

    # Negative rate limit
    with pytest.raises(ConfigValidationError) as exc:
        BotConfig(bot_token=valid_token, rate_limit_seconds=-0.5).validate()
    assert "RATE_LIMIT_SECONDS" in str(exc.value)

    # Concurrent downloads < 1
    with pytest.raises(ConfigValidationError) as exc:
        BotConfig(bot_token=valid_token, max_concurrent_downloads=0).validate()
    assert "MAX_CONCURRENT_DOWNLOADS" in str(exc.value)

    # Max size <= 0
    with pytest.raises(ConfigValidationError) as exc:
        BotConfig(bot_token=valid_token, default_max_size_gb=0).validate()
    assert "DEFAULT_MAX_SIZE_GB" in str(exc.value)

    # Chunk size < 1
    with pytest.raises(ConfigValidationError) as exc:
        BotConfig(bot_token=valid_token, download_chunk_size_kb=0).validate()
    assert "DOWNLOAD_CHUNK_SIZE_KB" in str(exc.value)

    # Invalid log level
    with pytest.raises(ConfigValidationError) as exc:
        BotConfig(bot_token=valid_token, log_level="SUPER_VERBOSE").validate()
    assert "LOG_LEVEL" in str(exc.value)


@pytest.mark.asyncio
async def test_unauthorized_user_cannot_claim_admin(tmp_path):
    """Security Test: Ensure first-admin setup cannot be claimed by an unauthorized Telegram user."""
    storage = StorageManager(db_path=tmp_path / "test_auth_sec.db")
    user_service = UserService(storage=storage)

    # Bot configured with trusted admin 12345
    trusted_admin_id = 12345
    untrusted_user_id = 99999
    config = BotConfig(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ12345",
        admin_ids=[trusted_admin_id],
        bot_mode="personal",
    )
    middleware = AuthMiddleware(user_service=user_service, config=config)

    handler = AsyncMock(return_value="PASSED")
    msg = MagicMock(spec=Message)
    msg.text = "/start"
    msg.answer = AsyncMock()

    # 1. Untrusted user sends /start before any admin has initialized DB
    data_unauth = {"event_from_user": User(id=untrusted_user_id, is_bot=False, first_name="Untrusted")}
    res = await middleware(handler, msg, data_unauth)
    # Blocked in personal mode, handler must not run
    assert res is None
    msg.answer.assert_called_once()
    assert "Access Restricted" in msg.answer.call_args[0][0]

    # Untrusted user attempts to directly invoke handle_claim_admin callback
    cb_hack = AsyncMock(spec=CallbackQuery)
    cb_hack.from_user = User(id=untrusted_user_id, is_bot=False, first_name="Untrusted")
    cb_hack.answer = AsyncMock()
    unauth_rec = await user_service.get_or_create_user(untrusted_user_id)
    await handle_claim_admin(
        cb_hack,
        user_record=unauth_rec,
        user_service=user_service,
        config=config,
    )
    cb_hack.answer.assert_called_with(
        "🚫 Unauthorized: Your Telegram ID is not in TELEGRAM_ADMIN_IDS.",
        show_alert=True,
    )
    assert await user_service.is_admin(untrusted_user_id) is False

    # 2. Trusted admin sends /start and is auto-promoted
    data_trusted = {"event_from_user": User(id=trusted_admin_id, is_bot=False, first_name="Owner")}
    res_trusted = await middleware(handler, msg, data_trusted)
    assert res_trusted == "PASSED"
    assert data_trusted["user_record"].is_admin is True
    assert await user_service.is_admin(trusted_admin_id) is True


@pytest.mark.asyncio
async def test_multi_user_mode_permissions(tmp_path):
    """Verify that multi-user mode allows guests to browse while reserving admin actions."""
    storage = StorageManager(db_path=tmp_path / "test_multi_user.db")
    user_service = UserService(storage=storage)

    config = BotConfig(
        bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ12345",
        admin_ids=[1001],
        bot_mode="multi-user",
    )
    middleware = AuthMiddleware(user_service=user_service, config=config)

    handler = AsyncMock(return_value="PASSED")
    msg = MagicMock(spec=Message)
    msg.text = "/search Inception"
    msg.answer = AsyncMock()

    # Guest user (not admin) can pass through
    guest_id = 5555
    data_guest = {"event_from_user": User(id=guest_id, is_bot=False, first_name="Guest")}
    res = await middleware(handler, msg, data_guest)
    assert res == "PASSED"
    assert data_guest["user_record"].is_admin is False


def test_storage_and_downloader_env_resolution(tmp_path, monkeypatch):
    """Verify that StorageManager, DownloadManager, and HTTPDownloader honor environment variables."""
    custom_db = tmp_path / "env_db" / "data.db"
    custom_dl = tmp_path / "env_downloads"

    monkeypatch.setenv("DATABASE_PATH", str(custom_db))
    monkeypatch.setenv("DOWNLOAD_DIR", str(custom_dl))
    monkeypatch.setenv("DOWNLOAD_CHUNK_SIZE_KB", "128")

    storage = StorageManager()
    assert storage.db_path == custom_db.resolve()
    assert custom_db.parent.exists()

    dl_mgr = DownloadManager()
    assert dl_mgr.download_dir == custom_dl.resolve()
    assert custom_dl.exists()

    http_dl = HTTPDownloader()
    assert http_dl.chunk_size == 128 * 1024
