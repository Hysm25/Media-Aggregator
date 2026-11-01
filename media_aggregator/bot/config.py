"""Configuration settings for Telegram Bot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from media_aggregator.downloader.manager import DEFAULT_DOWNLOAD_DIR


@dataclass
class BotConfig:
    """Telegram Bot runtime configuration."""

    bot_token: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", "").strip())
    admin_ids: List[int] = field(default_factory=list)
    download_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("MEDIA_AGGREGATOR_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR))
    )
    rate_limit_seconds: float = 0.8

    def __post_init__(self) -> None:
        raw_admins = os.environ.get("TELEGRAM_ADMIN_IDS", "").strip()
        if raw_admins and not self.admin_ids:
            for part in raw_admins.split(","):
                part = part.strip()
                if part.isdigit():
                    self.admin_ids.append(int(part))
        self.download_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(
        cls,
        token: Optional[str] = None,
        admin_id: Optional[int] = None,
        download_dir: Optional[str | Path] = None,
    ) -> BotConfig:
        """Create BotConfig with optional explicit overrides."""
        cfg = cls()
        if token:
            cfg.bot_token = token.strip()
        if admin_id is not None and admin_id not in cfg.admin_ids:
            cfg.admin_ids.append(admin_id)
        if download_dir:
            cfg.download_dir = Path(download_dir)
            cfg.download_dir.mkdir(parents=True, exist_ok=True)
        return cfg
