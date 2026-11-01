"""Cinemeta official metadata and catalog provider implementation."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any, Dict, List, Optional, Union
from media_aggregator.models import AddonManifest, EpisodeItem, MediaItem, MediaType, StreamSource
from media_aggregator.providers.base import BaseProvider

logger = logging.getLogger("media_aggregator.providers.cinemeta")


class CinemetaProvider(BaseProvider):
    """Cinemeta official Stremio add-on providing IMDb/TheMovieDb metadata and catalogs."""

    def __init__(self, base_url: str = "https://v3-cinemeta.strem.io", timeout: float = 12.0):
        super().__init__(name="Cinemeta", base_url=base_url, timeout=timeout)
        # Pre-seed default manifest conforming to Stremio protocol
        self._manifest = AddonManifest(
            id="com.linvo.cinemeta",
            name="Cinemeta",
            version="3.0.12",
            description="Official movie and series catalog with IMDb and TheMovieDb metadata.",
            resources=["catalog", "meta"],
            types=["movie", "series"],
            id_prefixes=["tt"],
            catalogs=[
                {"type": "movie", "id": "top", "name": "Popular Movies", "extra": [{"name": "search"}]},
                {"type": "series", "id": "top", "name": "Popular Series", "extra": [{"name": "search"}]},
            ],
        )

    def _parse_meta_dict(self, item: Dict[str, Any], default_type: MediaType) -> MediaItem:
        """Parse raw Cinemeta meta object into a MediaItem."""
        m_id = item.get("id") or item.get("imdb_id") or ""
        title = item.get("name") or item.get("title") or "Unknown Title"
        type_str = item.get("type", default_type.value)
        try:
            m_type = MediaType(type_str)
        except ValueError:
            m_type = default_type

        # Support both 'year' and Stremio's 'releaseInfo' (e.g. '2008-2013' for series)
        raw_year = item.get("year") or item.get("releaseInfo")
        year = str(raw_year) if raw_year else None

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
            s_num = v.get("season") if v.get("season") is not None else 1
            e_num = v.get("number") if v.get("number") is not None else v.get("episode", 1)
            v_id = v.get("id", f"{m_id}:{s_num}:{e_num}")
            episodes.append(
                EpisodeItem(
                    id=v_id,
                    season=s_num,
                    episode=e_num,
                    title=v.get("name") or v.get("title") or f"Episode {e_num}",
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

    def search(self, query: str, media_type: Optional[MediaType] = None) -> List[MediaItem]:
        """Search Cinemeta catalog by title or keyword. If media_type is None, searches both movies and series."""
        if media_type is None:
            results: List[MediaItem] = []
            seen_ids = set()
            for m_type in (MediaType.MOVIE, MediaType.SERIES):
                sub_results = self.search(query, media_type=m_type)
                for item in sub_results:
                    if item.id and item.id not in seen_ids:
                        seen_ids.add(item.id)
                        results.append(item)
            return results

        encoded_query = urllib.parse.quote(query)
        type_str = media_type.value
        url = f"{self.base_url}/catalog/{type_str}/top/search={encoded_query}.json"

        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            metas = data.get("metas", [])
            return [self._parse_meta_dict(m, media_type) for m in metas]
        except Exception as e:
            logger.warning(f"Cinemeta search failed for '{query}' (type={type_str}): {e}")
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
        except Exception as e:
            logger.warning(f"Cinemeta catalog fetch failed for {type_str}/{catalog_id}: {e}")
            return []

    def get_metadata(
        self,
        media_id_or_type: Optional[Union[MediaType, str]] = None,
        media_id: Optional[str] = None,
        media_type: Optional[MediaType] = None,
    ) -> Optional[MediaItem]:
        """Retrieve full media metadata including cast, crew, and episode list.
        
        Supports both (media_type, media_id) and (media_id, media_type=...) calling conventions.
        If media_type is None, tries MediaType.MOVIE then MediaType.SERIES.
        """
        if isinstance(media_id_or_type, MediaType):
            m_type = media_id_or_type
            m_id = media_id or ""
        elif isinstance(media_id_or_type, str):
            m_id = str(media_id_or_type)
            m_type = media_type
        else:
            m_id = media_id or ""
            m_type = media_type

        if m_type is None:
            # Probe MOVIE then SERIES to find correct metadata
            for candidate in (MediaType.MOVIE, MediaType.SERIES):
                item = self._fetch_meta_by_type(candidate, m_id)
                if item and (item.synopsis or item.episodes or item.cast):
                    return item
            return None

        return self._fetch_meta_by_type(m_type, m_id)

    def _fetch_meta_by_type(self, media_type: MediaType, media_id: str) -> Optional[MediaItem]:
        """Fetch metadata for a confirmed media_type and media_id."""
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
        except Exception as e:
            logger.debug(f"Cinemeta meta fetch failed for {type_str}/{media_id}: {e}")
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
