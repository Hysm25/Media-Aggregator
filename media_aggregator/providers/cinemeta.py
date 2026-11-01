"""Cinemeta metadata and catalog discovery provider."""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional
from media_aggregator.models import EpisodeItem, MediaItem, MediaType, StreamSource
from media_aggregator.providers.base import BaseProvider


class CinemetaProvider(BaseProvider):
    """Cinemeta metadata and catalog provider (official Stremio discovery source)."""

    def __init__(
        self,
        base_url: str = "https://v3-cinemeta.strem.io",
        timeout: float = 10.0,
    ):
        super().__init__(name="Cinemeta", base_url=base_url, timeout=timeout)

    def _parse_meta_dict(self, item: Dict[str, Any], default_type: MediaType) -> MediaItem:
        """Parse raw Cinemeta meta object into a MediaItem."""
        m_id = item.get("id") or item.get("imdb_id") or ""
        title = item.get("name") or "Unknown Title"
        type_str = item.get("type", default_type.value)
        try:
            m_type = MediaType(type_str)
        except ValueError:
            m_type = default_type

        year = str(item.get("year", "")) if item.get("year") else None
        poster = item.get("poster")
        background = item.get("background")
        synopsis = item.get("description") or item.get("overview")
        genres = item.get("genres") or item.get("genre") or []
        if isinstance(genres, str):
            genres = [g.strip() for g in genres.split(",")]

        cast = item.get("cast") or []
        if isinstance(cast, str):
            cast = [c.strip() for c in cast.split(",")]

        director = item.get("director")
        if isinstance(director, list):
            director = ", ".join(director)

        imdb_rating = str(item.get("imdbRating", "")) if item.get("imdbRating") else None
        runtime = str(item.get("runtime", "")) if item.get("runtime") else None

        # Parse TV series episodes if available
        episodes: List[EpisodeItem] = []
        raw_videos = item.get("videos", [])
        for v in raw_videos:
            v_id = v.get("id", f"{m_id}:{v.get('season', 1)}:{v.get('episode', 1)}")
            episodes.append(
                EpisodeItem(
                    id=v_id,
                    season=v.get("season", 1),
                    episode=v.get("number") or v.get("episode", 1),
                    title=v.get("name") or f"Episode {v.get('number', 1)}",
                    overview=v.get("overview") or v.get("description"),
                    released=v.get("released") or v.get("firstAired"),
                    thumbnail=v.get("thumbnail"),
                    rating=str(v.get("rating", "")) if v.get("rating") else None,
                )
            )

        return MediaItem(
            id=m_id,
            title=title,
            type=m_type,
            year=year,
            poster=poster,
            background=background,
            synopsis=synopsis,
            genres=genres,
            cast=cast,
            director=director,
            imdb_rating=imdb_rating,
            runtime=runtime,
            episodes=episodes,
        )

    def search(self, query: str, media_type: MediaType = MediaType.MOVIE) -> List[MediaItem]:
        """Search Cinemeta catalog by title or keyword."""
        encoded_query = urllib.parse.quote(query)
        type_str = media_type.value
        url = f"{self.base_url}/catalog/{type_str}/top/search={encoded_query}.json"

        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            metas = data.get("metas", [])
            return [self._parse_meta_dict(m, media_type) for m in metas]
        except Exception:
            return []

    def get_catalog(
        self,
        media_type: MediaType = MediaType.MOVIE,
        catalog_id: str = "top",
        extra: Optional[Dict[str, Any]] = None,
    ) -> List[MediaItem]:
        """Browse catalog items (e.g. top movies, popular series)."""
        type_str = media_type.value
        extra_parts = []
        if extra:
            for k, v in extra.items():
                extra_parts.append(f"{k}={urllib.parse.quote(str(v))}")

        extra_str = f"/{'&'.join(extra_parts)}" if extra_parts else ""
        url = f"{self.base_url}/catalog/{type_str}/{catalog_id}{extra_str}.json"

        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            metas = data.get("metas", [])
            return [self._parse_meta_dict(m, media_type) for m in metas]
        except Exception:
            return []

    def get_metadata(self, media_type: MediaType, media_id: str) -> Optional[MediaItem]:
        """Retrieve full media metadata including cast, crew, and episode list."""
        type_str = media_type.value
        url = f"{self.base_url}/meta/{type_str}/{media_id}.json"

        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            meta = data.get("meta")
            if not meta:
                return None
            return self._parse_meta_dict(meta, media_type)
        except Exception:
            return None

    def get_streams(
        self,
        media_type: MediaType,
        media_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> List[StreamSource]:
        """Cinemeta is a metadata-only provider, returning an empty list of streams."""
        return []
