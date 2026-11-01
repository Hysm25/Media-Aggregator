"""Abstract base class and interfaces for Stremio / Torrentio compatible providers."""

from __future__ import annotations

import abc
import urllib.parse
from typing import Any, Dict, List, Optional, Union
import requests
from media_aggregator.models import AddonManifest, MediaItem, MediaType, StreamSource


class BaseProvider(abc.ABC):
    """Abstract interface for all media and streaming providers."""

    def __init__(
        self,
        name: str,
        base_url: str,
        timeout: float = 10.0,
        headers: Optional[Dict[str, str]] = None,
        config_options: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.config_options = config_options or {}
        self.session = requests.Session()
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Stremio/4.4.168",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if headers:
            default_headers.update(headers)
        self.session.headers.update(default_headers)
        self._manifest: Optional[AddonManifest] = None

    def fetch_manifest(self) -> AddonManifest:
        """Fetch and cache addon manifest."""
        url = f"{self.base_url}/manifest.json"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        self._manifest = AddonManifest(
            id=data.get("id", ""),
            name=data.get("name", self.name),
            version=data.get("version", "1.0.0"),
            description=data.get("description"),
            resources=data.get("resources", []),
            types=data.get("types", []),
            catalogs=data.get("catalogs", []),
            id_prefixes=data.get("idPrefixes", []),
            icon=data.get("icon"),
            background=data.get("background"),
        )
        return self._manifest

    @property
    def manifest(self) -> Optional[AddonManifest]:
        return self._manifest

    def supports_resource(self, resource_name: str, media_type: Optional[MediaType] = None) -> bool:
        """Check if provider manifest supports a specific resource (catalog, meta, stream)."""
        resources = []
        if self._manifest and self._manifest.resources:
            resources = self._manifest.resources
        elif self.config_options and self.config_options.get("resources"):
            resources = self.config_options.get("resources")
        else:
            try:
                self.fetch_manifest()
                if self._manifest:
                    resources = self._manifest.resources
            except Exception:
                return False

        if not resources:
            return False

        type_val = media_type.value if media_type else None

        for res in resources:
            if isinstance(res, str) and res == resource_name:
                if type_val is None:
                    return True
                # Check top-level manifest types if defined
                manifest_types = []
                if self._manifest and self._manifest.types:
                    manifest_types = self._manifest.types
                elif self.config_options and self.config_options.get("types"):
                    manifest_types = self.config_options.get("types")
                if manifest_types:
                    return type_val in manifest_types
                return True
            elif isinstance(res, dict) and res.get("name") == resource_name:
                if type_val is None:
                    return True
                res_types = res.get("types", [])
                if res_types:
                    return type_val in res_types
                manifest_types = self._manifest.types if self._manifest else []
                if manifest_types:
                    return type_val in manifest_types
                return True
        return False

    def supports_id_prefix(self, media_id: str, resource_name: Optional[str] = None) -> bool:
        """Check if provider supports the given media ID prefix (e.g. 'tt', 'kitsu')."""
        prefixes = []
        # Check resource-specific idPrefixes first if available
        if resource_name and self._manifest and self._manifest.resources:
            for res in self._manifest.resources:
                if isinstance(res, dict) and res.get("name") == resource_name:
                    if "idPrefixes" in res:
                        prefixes = res.get("idPrefixes", [])
                        break
        # Fall back to top-level idPrefixes
        if not prefixes:
            if self._manifest and self._manifest.id_prefixes:
                prefixes = self._manifest.id_prefixes
            elif self.config_options and self.config_options.get("id_prefixes"):
                prefixes = self.config_options.get("id_prefixes")

        if not prefixes:
            return True  # If no prefixes declared, provider accepts any ID

        return any(media_id.startswith(p) for p in prefixes)

    def search(self, query: str, media_type: Optional[MediaType] = None) -> List[MediaItem]:
        """Search catalog for movies or series. Defaults to empty if unsupported."""
        return []

    def get_catalog(
        self,
        media_type: MediaType = MediaType.MOVIE,
        catalog_id: str = "top",
        extra: Optional[Dict[str, Any]] = None,
    ) -> List[MediaItem]:
        """Fetch items from a catalog."""
        return []

    def get_metadata(
        self,
        media_id_or_type: Optional[Union[MediaType, str]] = None,
        media_id: Optional[str] = None,
        media_type: Optional[MediaType] = None,
    ) -> Optional[MediaItem]:
        """Fetch detailed metadata for a movie or TV series.
        
        Supports both (media_type, media_id) and (media_id, media_type=...) calling conventions.
        """
        return None

    @abc.abstractmethod
    def get_streams(
        self,
        media_type: MediaType,
        media_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> List[StreamSource]:
        """Retrieve streaming/torrent sources for a media item."""
        pass
