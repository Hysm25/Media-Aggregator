"""Generic Stremio Add-on Provider supporting any Stremio v2/v3 compatible endpoint."""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional
from media_aggregator.models import EpisodeItem, MediaItem, MediaType, StreamSource
from media_aggregator.parser import parse_generic_stream
from media_aggregator.providers.base import BaseProvider


class GenericStremioProvider(BaseProvider):
    """Universal provider for any standard Stremio Add-on endpoint."""

    def __init__(
        self,
        name: str,
        base_url: str,
        timeout: float = 10.0,
    ):
        super().__init__(name=name, base_url=base_url, timeout=timeout)

    def _parse_item_dict(self, item: Dict[str, Any], default_type: MediaType) -> MediaItem:
        m_id = item.get("id", "")
        title = item.get("name") or "Unknown"
        type_str = item.get("type", default_type.value)
        try:
            m_type = MediaType(type_str)
        except ValueError:
            m_type = default_type

        genres = item.get("genres") or []
        cast = item.get("cast") or []
        episodes = []
        for v in item.get("videos", []):
            episodes.append(
                EpisodeItem(
                    id=v.get("id", f"{m_id}:{v.get('season', 1)}:{v.get('number', 1)}"),
                    season=v.get("season", 1),
                    episode=v.get("number") or v.get("episode", 1),
                    title=v.get("name", "Episode"),
                    overview=v.get("overview"),
                    released=v.get("released"),
                    thumbnail=v.get("thumbnail"),
                )
            )

        return MediaItem(
            id=m_id,
            title=title,
            type=m_type,
            year=str(item.get("year", "")) if item.get("year") else None,
            poster=item.get("poster"),
            background=item.get("background"),
            synopsis=item.get("description"),
            genres=genres,
            cast=cast,
            director=item.get("director"),
            imdb_rating=str(item.get("imdbRating", "")) if item.get("imdbRating") else None,
            runtime=str(item.get("runtime", "")) if item.get("runtime") else None,
            episodes=episodes,
        )

    def search(self, query: str, media_type: MediaType = MediaType.MOVIE) -> List[MediaItem]:
        """Query catalog search if supported by the addon."""
        type_str = media_type.value
        encoded_query = urllib.parse.quote(query)

        # Try standard catalog search endpoint
        url = f"{self.base_url}/catalog/{type_str}/top/search={encoded_query}.json"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                metas = data.get("metas", [])
                return [self._parse_item_dict(m, media_type) for m in metas]
        except Exception:
            pass
        return []

    def get_metadata(self, media_type: MediaType, media_id: str) -> Optional[MediaItem]:
        """Fetch media metadata if supported."""
        type_str = media_type.value
        url = f"{self.base_url}/meta/{type_str}/{media_id}.json"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                meta = data.get("meta")
                if meta:
                    return self._parse_item_dict(meta, media_type)
        except Exception:
            pass
        return None

    def get_streams(
        self,
        media_type: MediaType,
        media_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> List[StreamSource]:
        """Fetch stream items from the addon's stream endpoint."""
        type_str = media_type.value
        if media_type == MediaType.SERIES and season is not None and episode is not None:
            target_id = f"{media_id}:{season}:{episode}"
        else:
            target_id = media_id

        url = f"{self.base_url}/stream/{type_str}/{target_id}.json"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200:
                return []
            data = resp.json()
            raw_streams = data.get("streams", [])
            results = []
            for item in raw_streams:
                results.append(parse_generic_stream(item, provider_name=self.name))
            return results
        except Exception:
            return []
