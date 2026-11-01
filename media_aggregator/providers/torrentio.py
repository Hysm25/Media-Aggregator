"""Torrentio streaming provider implementation with full configuration support."""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional
from media_aggregator.models import MediaType, StreamSource
from media_aggregator.parser import parse_torrentio_stream
from media_aggregator.providers.base import BaseProvider

DEFAULT_TORRENTIO_PROVIDERS = [
    "yts",
    "eztv",
    "rarbg",
    "1337x",
    "thepiratebay",
    "kickasstorrents",
    "torrentgalaxy",
    "magnetdl",
    "nyaasi",
    "tokyotosho",
]


class TorrentioProvider(BaseProvider):
    """Torrentio add-on provider for torrent index aggregation and debrid streaming."""

    def __init__(
        self,
        base_url: str = "https://torrentio.strem.fun",
        timeout: float = 12.0,
        providers: Optional[List[str]] = None,
        sort: str = "qualitysize",
        quality_filter: Optional[List[str]] = None,
        limit: Optional[int] = None,
        debrid_provider: Optional[str] = None,
        debrid_api_key: Optional[str] = None,
        debrid_options: Optional[List[str]] = None,
        custom_config_path: Optional[str] = None,
    ):
        super().__init__(name="Torrentio", base_url=base_url, timeout=timeout)
        self.providers = providers
        self.sort = sort
        self.quality_filter = quality_filter
        self.limit = limit
        self.debrid_provider = debrid_provider
        self.debrid_api_key = debrid_api_key
        self.debrid_options = debrid_options
        self.custom_config_path = custom_config_path

    def build_config_path(self) -> str:
        """Construct Torrentio's pipe-delimited configuration path."""
        if self.custom_config_path:
            return self.custom_config_path.strip("/")

        parts: List[str] = []

        if self.providers:
            parts.append(f"providers={','.join(self.providers)}")

        if self.sort:
            parts.append(f"sort={self.sort}")

        if self.quality_filter:
            parts.append(f"qualityfilter={','.join(self.quality_filter)}")

        if self.limit:
            parts.append(f"limit={self.limit}")

        if self.debrid_options:
            parts.append(f"debridoptions={','.join(self.debrid_options)}")

        if self.debrid_provider and self.debrid_api_key:
            parts.append(f"{self.debrid_provider}={self.debrid_api_key}")

        return "|".join(parts)

    def get_effective_base_url(self) -> str:
        """Get the base URL including configured parameters."""
        config_path = self.build_config_path()
        if config_path:
            return f"{self.base_url}/{config_path}"
        return self.base_url

    def get_streams(
        self,
        media_type: MediaType,
        media_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> List[StreamSource]:
        """Fetch torrent and streaming sources from Torrentio."""
        type_str = media_type.value

        # For series, Stremio format is {imdb_id}:{season}:{episode}
        if media_type == MediaType.SERIES and season is not None and episode is not None:
            target_id = f"{media_id}:{season}:{episode}"
        else:
            target_id = media_id

        effective_url = self.get_effective_base_url()
        url = f"{effective_url}/stream/{type_str}/{target_id}.json"

        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            raw_streams = data.get("streams", [])
            results = []
            for item in raw_streams:
                stream = parse_torrentio_stream(item, provider_name=self.name)
                results.append(stream)
            return results
        except Exception:
            return []
