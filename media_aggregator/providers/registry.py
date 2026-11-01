"""Provider registry managing active providers and registration of new Stremio addons."""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple
import requests
from media_aggregator.models import AddonConfig, AddonManifest, MediaType
from media_aggregator.providers.base import BaseProvider
from media_aggregator.providers.cinemeta import CinemetaProvider
from media_aggregator.providers.generic import GenericStremioProvider
from media_aggregator.providers.torrentio import TorrentioProvider
from media_aggregator.storage import StorageManager

logger = logging.getLogger("media_aggregator.providers.registry")


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
            return GenericStremioProvider(name=config.name, base_url=config.base_url, config_options=opts)

    def get_active_providers(self) -> List[BaseProvider]:
        """Fetch all enabled providers sorted by priority."""
        configs = self.storage.get_addons(enabled_only=True)
        return [self.get_provider_instance(c) for c in configs]

    def get_discovery_provider(self, media_type: Optional[MediaType] = None) -> BaseProvider:
        """Get the primary provider used for catalog and search discovery (Cinemeta by default)."""
        providers = self.get_active_providers()
        if media_type == MediaType.ANIME:
            for p in providers:
                if "kitsu" in p.name.lower() or "anime" in p.name.lower():
                    return p
        for p in providers:
            if isinstance(p, CinemetaProvider):
                return p
        # Fallback to any provider supporting search
        for p in providers:
            if p.supports_resource("catalog", media_type=media_type) or p.supports_resource("meta", media_type=media_type):
                return p
        # Default fallback
        return CinemetaProvider()

    def get_catalog_providers(self, media_type: Optional[MediaType] = None) -> List[BaseProvider]:
        """Get all active providers capable of returning catalogs and search results."""
        providers = self.get_active_providers()
        catalog_providers = [
            p for p in providers
            if p.supports_resource("catalog", media_type=media_type)
        ]
        if not catalog_providers:
            return [self.get_discovery_provider(media_type=media_type)]
        return catalog_providers

    def get_metadata_providers(
        self,
        media_type: Optional[MediaType] = None,
        media_id: Optional[str] = None,
    ) -> List[BaseProvider]:
        """Get all active providers capable of returning full media metadata."""
        providers = self.get_active_providers()
        meta_providers = [
            p for p in providers
            if p.supports_resource("meta", media_type=media_type)
            and (not media_id or p.supports_id_prefix(media_id, resource_name="meta"))
        ]
        if not meta_providers:
            return [self.get_discovery_provider(media_type=media_type)]
        return meta_providers

    def get_stream_providers(
        self,
        media_type: Optional[MediaType] = None,
        media_id: Optional[str] = None,
    ) -> List[BaseProvider]:
        """Get all active providers capable of returning streams, respecting declared capabilities."""
        providers = self.get_active_providers()
        return [
            p for p in providers
            if p.supports_resource("stream", media_type=media_type)
            and (not media_id or p.supports_id_prefix(media_id, resource_name="stream"))
        ]

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
                headers={"User-Agent": "MediaSourceAggregator/1.0.0 (Stremio/Compatible; Linux)"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            addon_id = data.get("id")
            if not addon_id:
                return False, "Addon manifest does not contain a valid 'id' field.", None

            name = data.get("name", addon_id)
            opts = {
                "resources": data.get("resources", []),
                "types": data.get("types", []),
                "catalogs": data.get("catalogs", []),
                "id_prefixes": data.get("idPrefixes", []),
            }
            config = AddonConfig(
                id=addon_id,
                name=name,
                manifest_url=manifest_url,
                base_url=base_url,
                enabled=True,
                priority=priority,
                config_options=opts,
            )
            self.storage.save_addon(config)
            return True, f"Successfully registered '{name}' ({addon_id}).", config
        except Exception as e:
            return False, f"Failed to retrieve or parse manifest from {manifest_url}: {e}", None
