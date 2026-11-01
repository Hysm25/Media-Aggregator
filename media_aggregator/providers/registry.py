"""Provider registry managing active providers and registration of new Stremio addons."""

from __future__ import annotations

from typing import List, Optional, Tuple
import requests
from media_aggregator.models import AddonConfig, AddonManifest
from media_aggregator.providers.base import BaseProvider
from media_aggregator.providers.cinemeta import CinemetaProvider
from media_aggregator.providers.generic import GenericStremioProvider
from media_aggregator.providers.torrentio import TorrentioProvider
from media_aggregator.storage import StorageManager


class ProviderRegistry:
    """Registry that instantiates and orchestrates Stremio add-on providers."""

    def __init__(self, storage: Optional[StorageManager] = None):
        self.storage = storage or StorageManager()

    def get_provider_instance(self, config: AddonConfig) -> BaseProvider:
        """Instantiate appropriate BaseProvider subclass from AddonConfig."""
        opts = config.config_options or {}

        if "torrentio" in config.id.lower() or "torrentio" in config.base_url.lower():
            return TorrentioProvider(
                base_url=config.base_url,
                providers=opts.get("providers"),
                sort=opts.get("sort", "qualitysize"),
                quality_filter=opts.get("qualityfilter"),
                limit=opts.get("limit"),
                debrid_provider=opts.get("debrid_provider"),
                debrid_api_key=opts.get("debrid_api_key"),
                custom_config_path=opts.get("custom_config_path"),
            )
        elif "cinemeta" in config.id.lower() or "cinemeta" in config.base_url.lower():
            return CinemetaProvider(base_url=config.base_url)
        else:
            return GenericStremioProvider(name=config.name, base_url=config.base_url)

    def get_active_providers(self) -> List[BaseProvider]:
        """Fetch all enabled providers sorted by priority."""
        configs = self.storage.get_addons(enabled_only=True)
        return [self.get_provider_instance(c) for c in configs]

    def get_discovery_provider(self) -> BaseProvider:
        """Get the primary provider used for catalog and search discovery (Cinemeta by default)."""
        providers = self.get_active_providers()
        for p in providers:
            if isinstance(p, CinemetaProvider):
                return p
        # Fallback to any provider supporting search
        for p in providers:
            if p.supports_resource("catalog") or p.supports_resource("meta"):
                return p
        # Default fallback
        return CinemetaProvider()

    def get_stream_providers(self) -> List[BaseProvider]:
        """Get all active providers capable of returning streams."""
        providers = self.get_active_providers()
        # Filter to those that aren't purely metadata (Cinemeta is meta-only)
        return [p for p in providers if not isinstance(p, CinemetaProvider)]

    def register_addon_by_url(self, manifest_or_base_url: str, priority: int = 10) -> Tuple[bool, str, Optional[AddonConfig]]:
        """Validate, probe, and register a new Stremio addon from its URL."""
        url = manifest_or_base_url.strip()
        if not url.endswith("/manifest.json"):
            manifest_url = f"{url.rstrip('/')}/manifest.json"
            base_url = url.rstrip("/")
        else:
            manifest_url = url
            base_url = url[: -len("/manifest.json")].rstrip("/")

        try:
            resp = requests.get(
                manifest_url,
                headers={"User-Agent": "MediaSourceAggregator/1.0.0"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            addon_id = data.get("id")
            if not addon_id:
                return False, "Addon manifest does not contain a valid 'id' field.", None

            name = data.get("name", addon_id)
            config = AddonConfig(
                id=addon_id,
                name=name,
                manifest_url=manifest_url,
                base_url=base_url,
                enabled=True,
                priority=priority,
            )
            self.storage.save_addon(config)
            return True, f"Successfully registered addon: {name} ({addon_id})", config
        except Exception as e:
            return False, f"Failed to connect or parse addon manifest: {str(e)}", None
