"""Stremio add-on registry management service."""

from __future__ import annotations

import asyncio
from typing import List, Optional, Tuple
import requests
from media_aggregator.models import AddonConfig, AddonManifest
from media_aggregator.storage import StorageManager


class AddonService:
    """Manages Stremio add-on manifests, registration, and toggles."""

    def __init__(self, storage: Optional[StorageManager] = None):
        self.storage = storage or StorageManager()

    async def list_addons(self, enabled_only: bool = False) -> List[AddonConfig]:
        """Fetch all registered add-on providers."""
        return await asyncio.to_thread(self.storage.get_addons, enabled_only=enabled_only)

    async def toggle_addon(self, addon_id: str, enabled: bool) -> bool:
        """Enable or disable an add-on."""
        return await asyncio.to_thread(self.storage.set_addon_enabled, addon_id, enabled)

    async def delete_addon(self, addon_id: str) -> bool:
        """Remove an add-on from database."""
        return await asyncio.to_thread(self.storage.delete_addon, addon_id)

    async def add_addon_from_manifest_url(self, manifest_url: str) -> Tuple[bool, str, Optional[AddonConfig]]:
        """Validate and register a new Stremio add-on manifest URL."""
        clean_url = manifest_url.strip()
        if not clean_url.endswith("/manifest.json"):
            if clean_url.endswith("/"):
                clean_url += "manifest.json"
            else:
                clean_url += "/manifest.json"

        def _fetch_and_save() -> Tuple[bool, str, Optional[AddonConfig]]:
            try:
                resp = requests.get(clean_url, timeout=10.0)
                if resp.status_code != 200:
                    return False, f"HTTP Error {resp.status_code} fetching manifest.", None

                data = resp.json()
                manifest = AddonManifest(**data)
                base_url = clean_url[: -len("/manifest.json")]

                config = AddonConfig(
                    id=manifest.id,
                    name=manifest.name,
                    manifest_url=clean_url,
                    base_url=base_url,
                    enabled=True,
                    priority=10,
                    config_options={
                        "resources": [
                            r.get("name") if isinstance(r, dict) else str(r)
                            for r in manifest.resources
                        ],
                        "types": manifest.types,
                    },
                )
                self.storage.save_addon(config)
                return True, f"Add-on '{manifest.name}' ({manifest.id}) installed successfully.", config
            except Exception as e:
                return False, f"Failed to parse manifest: {e}", None

        return await asyncio.to_thread(_fetch_and_save)
