"""Configuration settings and environment variable loader for Telegram Bot."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*args, **kwargs):  # type: ignore
        return False

from media_aggregator.downloader.manager import DEFAULT_DOWNLOAD_DIR
from media_aggregator.storage import DEFAULT_DB_PATH


class ConfigValidationError(ValueError):
    """Raised when runtime or environment configuration is invalid."""
    pass


@dataclass
class BotConfig:
    """Telegram Bot runtime configuration loaded from environment variables and CLI overrides."""

    bot_token: str = ""
    admin_ids: List[int] = field(default_factory=list)
    bot_mode: str = "personal"
    database_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)
    rate_limit_seconds: float = 0.8
    download_dir: Path = field(default_factory=lambda: DEFAULT_DOWNLOAD_DIR)
    max_concurrent_downloads: int = 3
    default_max_size_gb: float = 15.0
    download_chunk_size_kb: int = 1024
    log_level: str = "INFO"
    default_torrentio_url: str = "https://torrentio.strem.fun"
    default_cinemeta_url: str = "https://v3-cinemeta.strem.io"
    default_realdebrid_api_key: Optional[str] = None
    default_alldebrid_api_key: Optional[str] = None

    def __post_init__(self) -> None:
        if isinstance(self.database_path, str):
            self.database_path = Path(self.database_path)
        self.database_path = self.database_path.expanduser()

        if isinstance(self.download_dir, str):
            self.download_dir = Path(self.download_dir)
        self.download_dir = self.download_dir.expanduser()

    def validate(self, require_token: bool = True) -> None:
        """Validate all configuration attributes and raise ConfigValidationError on failure."""
        errors: List[str] = []

        # Validate token
        if require_token:
            if not self.bot_token or not self.bot_token.strip():
                errors.append(
                    "BOT_TOKEN is required. Provide it in .env, as an environment variable, "
                    "or pass --token to 'media-aggregator bot'."
                )
            else:
                token_val = self.bot_token.strip()
                # Bot token format: <bot_id>:<secret> (e.g., 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ)
                if not re.match(r"^\d+:[A-Za-z0-9_-]{20,}$", token_val):
                    errors.append(
                        f"Invalid BOT_TOKEN format: '{token_val}'. "
                        "Telegram bot tokens must match '<id>:<token_string>' format."
                    )

        # Validate bot mode
        normalized_mode = self.bot_mode.strip().lower()
        if normalized_mode not in ("personal", "multi-user"):
            errors.append(
                f"Invalid BOT_MODE: '{self.bot_mode}'. Must be either 'personal' or 'multi-user'."
            )
        else:
            self.bot_mode = normalized_mode

        # Validate admin IDs
        for aid in self.admin_ids:
            if not isinstance(aid, int) or aid <= 0:
                errors.append(f"Invalid admin ID '{aid}'. Admin IDs must be positive integers.")

        # Validate rate limits and download settings
        if self.rate_limit_seconds < 0:
            errors.append(f"RATE_LIMIT_SECONDS must be non-negative (got {self.rate_limit_seconds}).")

        if self.max_concurrent_downloads < 1:
            errors.append(f"MAX_CONCURRENT_DOWNLOADS must be at least 1 (got {self.max_concurrent_downloads}).")

        if self.default_max_size_gb <= 0:
            errors.append(f"DEFAULT_MAX_SIZE_GB must be greater than 0 (got {self.default_max_size_gb}).")

        if self.download_chunk_size_kb < 1:
            errors.append(f"DOWNLOAD_CHUNK_SIZE_KB must be at least 1 KB (got {self.download_chunk_size_kb}).")

        # Validate log level
        valid_log_levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        normalized_log = self.log_level.strip().upper()
        if normalized_log not in valid_log_levels:
            errors.append(
                f"Invalid LOG_LEVEL '{self.log_level}'. Must be one of: {', '.join(valid_log_levels)}."
            )
        else:
            self.log_level = normalized_log

        if errors:
            raise ConfigValidationError("Configuration validation failed:\n  • " + "\n  • ".join(errors))

        # Ensure directories exist
        try:
            self.download_dir.mkdir(parents=True, exist_ok=True)
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ConfigValidationError(f"Could not create storage/download directory: {e}") from e

    @classmethod
    def from_env(
        cls,
        dotenv_path: Optional[str | Path] = None,
        token: Optional[str] = None,
        admin_id: Optional[int] = None,
        admin_ids: Optional[List[int]] = None,
        download_dir: Optional[str | Path] = None,
        database_path: Optional[str | Path] = None,
        bot_mode: Optional[str] = None,
        validate: bool = False,
    ) -> BotConfig:
        """Create BotConfig loaded from .env and environment variables with optional CLI overrides."""
        # Load .env file without overriding existing environment variables
        if dotenv_path:
            load_dotenv(dotenv_path=Path(dotenv_path).expanduser(), override=False)
        else:
            load_dotenv(override=False)

        # Token: BOT_TOKEN or legacy TELEGRAM_BOT_TOKEN
        cfg_token = token or os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or ""
        cfg_token = cfg_token.strip()

        # Admin IDs: TELEGRAM_ADMIN_IDS (comma-separated)
        parsed_admins: List[int] = []
        if admin_ids is not None:
            parsed_admins.extend(admin_ids)
        else:
            raw_admins = os.environ.get("TELEGRAM_ADMIN_IDS", "").strip()
            if raw_admins:
                for part in raw_admins.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    if part.isdigit() and int(part) > 0:
                        parsed_admins.append(int(part))
                    else:
                        raise ConfigValidationError(
                            f"Invalid TELEGRAM_ADMIN_IDS value '{part}'. Expected positive integer."
                        )

        if admin_id is not None and admin_id not in parsed_admins:
            parsed_admins.append(admin_id)

        # Bot Mode
        cfg_mode = (bot_mode or os.environ.get("BOT_MODE") or "personal").strip().lower()

        # Database Path: DATABASE_PATH or legacy MEDIA_AGGREGATOR_DB
        raw_db = database_path or os.environ.get("DATABASE_PATH") or os.environ.get("MEDIA_AGGREGATOR_DB")
        cfg_db = Path(raw_db).expanduser() if raw_db else DEFAULT_DB_PATH

        # Download Dir: DOWNLOAD_DIR or legacy MEDIA_AGGREGATOR_DOWNLOAD_DIR
        raw_dl = download_dir or os.environ.get("DOWNLOAD_DIR") or os.environ.get("MEDIA_AGGREGATOR_DOWNLOAD_DIR")
        cfg_dl = Path(raw_dl).expanduser() if raw_dl else DEFAULT_DOWNLOAD_DIR

        # Rate Limit
        try:
            cfg_rate = float(os.environ.get("RATE_LIMIT_SECONDS", 0.8))
        except ValueError:
            raise ConfigValidationError(
                f"Invalid RATE_LIMIT_SECONDS '{os.environ.get('RATE_LIMIT_SECONDS')}'. Must be a numeric float."
            )

        # Download limits
        try:
            cfg_max_concurrent = int(os.environ.get("MAX_CONCURRENT_DOWNLOADS", 3))
        except ValueError:
            raise ConfigValidationError(
                f"Invalid MAX_CONCURRENT_DOWNLOADS '{os.environ.get('MAX_CONCURRENT_DOWNLOADS')}'. Must be an integer."
            )

        try:
            cfg_max_size_gb = float(os.environ.get("DEFAULT_MAX_SIZE_GB", 15.0))
        except ValueError:
            raise ConfigValidationError(
                f"Invalid DEFAULT_MAX_SIZE_GB '{os.environ.get('DEFAULT_MAX_SIZE_GB')}'. Must be a numeric float."
            )

        try:
            cfg_chunk_size_kb = int(os.environ.get("DOWNLOAD_CHUNK_SIZE_KB", 1024))
        except ValueError:
            raise ConfigValidationError(
                f"Invalid DOWNLOAD_CHUNK_SIZE_KB '{os.environ.get('DOWNLOAD_CHUNK_SIZE_KB')}'. Must be an integer."
            )

        # Log level
        cfg_log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()

        # Addon / provider URLs
        cfg_torrentio_url = os.environ.get("DEFAULT_TORRENTIO_URL", "https://torrentio.strem.fun").strip()
        cfg_cinemeta_url = os.environ.get("DEFAULT_CINEMETA_URL", "https://v3-cinemeta.strem.io").strip()
        cfg_rd_key = os.environ.get("DEFAULT_REALDEBRID_API_KEY")
        cfg_ad_key = os.environ.get("DEFAULT_ALLDEBRID_API_KEY")

        config = cls(
            bot_token=cfg_token,
            admin_ids=parsed_admins,
            bot_mode=cfg_mode,
            database_path=cfg_db,
            rate_limit_seconds=cfg_rate,
            download_dir=cfg_dl,
            max_concurrent_downloads=cfg_max_concurrent,
            default_max_size_gb=cfg_max_size_gb,
            download_chunk_size_kb=cfg_chunk_size_kb,
            log_level=cfg_log_level,
            default_torrentio_url=cfg_torrentio_url,
            default_cinemeta_url=cfg_cinemeta_url,
            default_realdebrid_api_key=cfg_rd_key.strip() if cfg_rd_key else None,
            default_alldebrid_api_key=cfg_ad_key.strip() if cfg_ad_key else None,
        )

        if validate:
            config.validate(require_token=True)

        return config
