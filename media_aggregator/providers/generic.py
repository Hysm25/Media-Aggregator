"""Generic Stremio Add-on Provider supporting any Stremio v2/v3 compatible endpoint."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any, Dict, List, Optional, Union
from media_aggregator.models import EpisodeItem, MediaItem, MediaType, StreamSource
from media_aggregator.parser import parse_generic_stream
from media_aggregator.providers.base import BaseProvider

logger = logging.getLogger("media_aggregator.providers.generic")


class GenericStremioProvider(BaseProvider):
    """Universal provider for any standard Stremio Add-on endpoint."""

    def __init__(
        self,
        name: str,
        base_url: str,
        timeout: float = 10.0,
        config_options: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name=name, base_url=base_url, timeout=timeout, config_options=config_options)

    def _parse_item_dict(self, item: Dict[str, Any], default_type: MediaType) -> MediaItem:
        m_id = item.get("id", "")
        title = item.get("name") or item.get("title") or "Unknown"
        type_str = item.get("type", default_type.value)
        try:
            m_type = MediaType(type_str)
        except ValueError:
            m_type = default_type

        # Support both 'year' and Stremio's 'releaseInfo'
        raw_year = item.get("year") or item.get("releaseInfo")
        year = str(raw_year) if raw_year else None

        genres = item.get("genres") or []
        cast = item.get("cast") or []
        episodes = []
        for v in item.get("videos", []):
            s_num = v.get("season", 1)
            e_num = v.get("number") or v.get("episode", 1)
            episodes.append(
                EpisodeItem(
                    id=v.get("id", f"{m_id}:{s_num}:{e_num}"),
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
            poster=item.get("poster"),
            background=item.get("background"),
            synopsis=item.get("description") or item.get("overview"),
            genres=genres,
            cast=cast,
            director=item.get("director"),
            imdb_rating=str(item.get("imdbRating", "")) if item.get("imdbRating") else None,
            runtime=str(item.get("runtime", "")) if item.get("runtime") else None,
            episodes=episodes,
        )

    def _find_catalog_id_for_search(self, media_type: MediaType) -> Optional[str]:
        """Find the appropriate catalog ID from the manifest that supports search."""
        if not self._manifest:
            try:
                self.fetch_manifest()
            except Exception:
                pass

        catalogs = []
        if self._manifest and self._manifest.catalogs:
            catalogs = self._manifest.catalogs
        elif self.config_options and self.config_options.get("catalogs"):
            catalogs = self.config_options.get("catalogs")

        if catalogs:
            type_str = media_type.value
            for cat in catalogs:
                if isinstance(cat, dict) and cat.get("type") == type_str:
                    extra = cat.get("extra", [])
                    has_search = any(
                        isinstance(e, dict) and e.get("name") == "search"
                        for e in extra
                    )
                    if not has_search:
                        has_search = "search" in cat.get("extraSupported", [])
                    if has_search:
                        return cat.get("id", "top")

            # Fallback to first catalog matching type
            for cat in catalogs:
                if isinstance(cat, dict) and cat.get("type") == type_str:
                    return cat.get("id", "top")

        return None

    def search(self, query: str, media_type: Optional[MediaType] = None) -> List[MediaItem]:
        """Query catalog search if supported by the addon."""
        if media_type is None:
            results: List[MediaItem] = []
            seen_ids = set()
            for m_type in (MediaType.MOVIE, MediaType.SERIES, MediaType.ANIME):
                for item in self.search(query, media_type=m_type):
                    if item.id and item.id not in seen_ids:
                        seen_ids.add(item.id)
                        results.append(item)
            return results

        type_str = media_type.value
        encoded_query = urllib.parse.quote(query)
        cat_id = self._find_catalog_id_for_search(media_type)
        if not cat_id:
            return []

        url = f"{self.base_url}/catalog/{type_str}/{cat_id}/search={encoded_query}.json"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                metas = data.get("metas", [])
                return [self._parse_item_dict(m, media_type) for m in metas]
        except Exception as e:
            logger.debug(f"Generic provider '{self.name}' search failed for '{query}': {e}")
        return []

    def get_metadata(
        self,
        media_id_or_type: Optional[Union[MediaType, str]] = None,
        media_id: Optional[Union[MediaType, str]] = None,
        media_type: Optional[Union[MediaType, str]] = None,
    ) -> Optional[MediaItem]:
        """Fetch media metadata if supported.
        
        Supports (media_type, media_id), (media_id, media_type), and (media_id) calling conventions.
        """
        m_id: str = ""
        m_type: Optional[MediaType] = None

        if isinstance(media_type, MediaType):
            m_type = media_type
        elif isinstance(media_type, str):
            try:
                m_type = MediaType(media_type.lower())
            except ValueError:
                pass

        if isinstance(media_id_or_type, MediaType):
            m_type = media_id_or_type
            if isinstance(media_id, str):
                m_id = media_id
        elif isinstance(media_id_or_type, str):
            val = media_id_or_type.strip()
            if val.lower() in ("movie", "series", "anime", "channel", "tv"):
                try:
                    m_type = MediaType(val.lower())
                except ValueError:
                    m_type = MediaType.SERIES
                if isinstance(media_id, str):
                    m_id = media_id
            else:
                m_id = val
                if isinstance(media_id, MediaType):
                    m_type = media_id
                elif isinstance(media_id, str) and media_id.lower() in ("movie", "series", "anime", "channel", "tv"):
                    try:
                        m_type = MediaType(media_id.lower())
                    except ValueError:
                        m_type = MediaType.SERIES

        if not m_id and isinstance(media_id, str):
            m_id = media_id

        if not m_id:
            return None

        if m_type is None:
            for candidate in (MediaType.MOVIE, MediaType.SERIES, MediaType.ANIME):
                item = self._fetch_meta_by_type(candidate, m_id)
                if item and (item.synopsis or item.episodes or item.cast):
                    return item
            return None

        return self._fetch_meta_by_type(m_type, m_id)

    def _fetch_meta_by_type(self, media_type: MediaType, media_id: str) -> Optional[MediaItem]:
        type_str = media_type.value
        url = f"{self.base_url}/meta/{type_str}/{media_id}.json"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                meta = data.get("meta")
                if meta:
                    return self._parse_item_dict(meta, media_type)
        except Exception as e:
            logger.debug(f"Generic provider '{self.name}' meta fetch failed: {e}")
        return None

    def get_streams(
        self,
        media_type: Union[MediaType, str],
        media_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> List[StreamSource]:
        """Fetch stream items from the addon's stream endpoint."""
        if isinstance(media_type, MediaType):
            m_type = media_type
            type_str = media_type.value
        else:
            type_str = str(media_type).lower()
            try:
                m_type = MediaType(type_str)
            except ValueError:
                m_type = MediaType.SERIES

        if ":" in media_id:
            target_id = media_id
        elif m_type == MediaType.SERIES and season is not None and episode is not None:
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
        except Exception as e:
            logger.debug(f"Generic provider '{self.name}' stream fetch failed: {e}")
            return []
