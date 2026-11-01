"""Abstract base class and interfaces for Stremio / Torrentio compatible providers."""

from __future__ import annotations

import abc
import urllib.parse
from typing import Any, Dict, List, Optional
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
            "User-Agent": "MediaSourceAggregator/1.0.0 (Stremio/Compatible; Linux)",
            "Accept": "application/json",
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

        for res in resources:
            if isinstance(res, str) and res == resource_name:
                return True
            elif isinstance(res, dict) and res.get("name") == resource_name:
                if media_type is None:
                    return True
                types = res.get("types", [])
                if not types or media_type.value in types:
                    return True
        return False

    def search(self, query: str, media_type: MediaType = MediaType.MOVIE) -> List[MediaItem]:
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

    def get_metadata(self, media_type: MediaType, media_id: str) -> Optional[MediaItem]:
        """Fetch detailed metadata for a movie or TV series."""
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
