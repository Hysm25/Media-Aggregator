"""SQLite-backed persistent storage for history, media cache, addons, and downloads."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from media_aggregator.models import (
    AddonConfig,
    DownloadRecord,
    DownloadStatus,
    EpisodeItem,
    MediaItem,
    MediaType,
    SourceType,
    StreamSource,
)

DEFAULT_DB_DIR = Path.home() / ".media_aggregator"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "data.db"


class StorageManager:
    """Manages SQLite persistent storage for media records, stream history, and downloads."""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path) if db_path else Path(os.environ.get("MEDIA_AGGREGATOR_DB", DEFAULT_DB_PATH))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create tables and default schema if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Media cache table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS media_cache (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL,
                    year TEXT,
                    poster TEXT,
                    background TEXT,
                    synopsis TEXT,
                    genres TEXT,
                    cast_members TEXT,
                    director TEXT,
                    imdb_rating TEXT,
                    runtime TEXT,
                    episodes_json TEXT,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Stream source discovery history
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS stream_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    info_hash TEXT,
                    url TEXT,
                    release_title TEXT,
                    resolution TEXT,
                    size_display TEXT,
                    seeders INTEGER,
                    raw_data TEXT,
                    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Downloads history
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_id TEXT NOT NULL,
                    media_title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    target_url TEXT NOT NULL,
                    local_path TEXT,
                    status TEXT NOT NULL,
                    total_bytes INTEGER DEFAULT 0,
                    downloaded_bytes INTEGER DEFAULT 0,
                    progress_percent REAL DEFAULT 0.0,
                    speed_bps REAL DEFAULT 0.0,
                    eta_seconds INTEGER,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
                """
            )

            # Addons registry
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS addons (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    manifest_url TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    priority INTEGER DEFAULT 10,
                    config_options TEXT DEFAULT '{}'
                )
                """
            )

            # Bookmarks
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS bookmarks (
                    media_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL,
                    year TEXT,
                    poster TEXT,
                    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            conn.commit()

        # Seed initial default providers if empty
        self.initialize_default_addons()

    def initialize_default_addons(self) -> None:
        """Seed default Cinemeta, Torrentio, and Anime Kitsu providers if table empty."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM addons")
            count = cursor.fetchone()["count"]
            if count == 0:
                default_addons = [
                    (
                        "com.linvo.cinemeta",
                        "Cinemeta (Official Catalog)",
                        "https://v3-cinemeta.strem.io/manifest.json",
                        "https://v3-cinemeta.strem.io",
                        1,
                        1,
                        "{}",
                    ),
                    (
                        "com.stremio.torrentio.addon",
                        "Torrentio (Scraper)",
                        "https://torrentio.strem.fun/manifest.json",
                        "https://torrentio.strem.fun",
                        1,
                        5,
                        "{}",
                    ),
                    (
                        "anime-kitsu",
                        "Anime Kitsu (Anime Streams)",
                        "https://anime-kitsu.strem.fun/manifest.json",
                        "https://anime-kitsu.strem.fun",
                        1,
                        10,
                        "{}",
                    ),
                ]
                cursor.executemany(
                    """
                    INSERT INTO addons (id, name, manifest_url, base_url, enabled, priority, config_options)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    default_addons,
                )
                conn.commit()

    # --- Media Cache ---

    def save_media_item(self, item: MediaItem) -> None:
        """Cache media details in database."""
        episodes_json = json.dumps([ep.model_dump() for ep in item.episodes]) if item.episodes else None
        genres_json = json.dumps(item.genres)
        cast_json = json.dumps(item.cast)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO media_cache (
                    id, title, type, year, poster, background, synopsis, genres, cast_members,
                    director, imdb_rating, runtime, episodes_json, cached_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    item.id,
                    item.title,
                    item.type.value,
                    item.year,
                    item.poster,
                    item.background,
                    item.synopsis,
                    genres_json,
                    cast_json,
                    item.director,
                    item.imdb_rating,
                    item.runtime,
                    episodes_json,
                ),
            )
            conn.commit()

    def get_media_item(self, media_id: str) -> Optional[MediaItem]:
        """Retrieve cached media item if available."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM media_cache WHERE id = ?", (media_id,)).fetchone()
            if not row:
                return None

            episodes = []
            if row["episodes_json"]:
                raw_eps = json.loads(row["episodes_json"])
                episodes = [EpisodeItem(**ep) for ep in raw_eps]

            return MediaItem(
                id=row["id"],
                title=row["title"],
                type=MediaType(row["type"]),
                year=row["year"],
                poster=row["poster"],
                background=row["background"],
                synopsis=row["synopsis"],
                genres=json.loads(row["genres"] or "[]"),
                cast=json.loads(row["cast_members"] or "[]"),
                director=row["director"],
                imdb_rating=row["imdb_rating"],
                runtime=row["runtime"],
                episodes=episodes,
            )

    # --- Stream History ---

    def record_stream_sources(self, media_id: str, sources: List[StreamSource]) -> None:
        """Record discovered stream sources for local tracking and audit."""
        rows = []
        for s in sources:
            raw_data = json.dumps(s.model_dump(), default=str)
            rows.append(
                (
                    media_id,
                    s.provider,
                    s.info_hash,
                    s.url,
                    s.release_title or s.title,
                    s.resolution,
                    s.size_display,
                    s.seeders,
                    raw_data,
                )
            )

        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO stream_history (
                    media_id, provider, info_hash, url, release_title, resolution, size_display, seeders, raw_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

    def get_stream_history(self, media_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve previously discovered stream history records."""
        with self._get_connection() as conn:
            if media_id:
                cursor = conn.execute(
                    "SELECT * FROM stream_history WHERE media_id = ? ORDER BY discovered_at DESC LIMIT ?",
                    (media_id, limit),
                )
            else:
                cursor = conn.execute("SELECT * FROM stream_history ORDER BY discovered_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # --- Downloads ---

    def create_download(
        self,
        media_id: str,
        media_title: str,
        source_type: SourceType,
        target_url: str,
        local_path: Optional[str] = None,
    ) -> int:
        """Create a new download record."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO downloads (
                    media_id, media_title, source_type, target_url, local_path, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (media_id, media_title, source_type.value, target_url, local_path, DownloadStatus.PENDING.value),
            )
            conn.commit()
            return cursor.lastrowid

    def update_download(
        self,
        download_id: int,
        status: Optional[DownloadStatus] = None,
        downloaded_bytes: Optional[int] = None,
        total_bytes: Optional[int] = None,
        progress_percent: Optional[float] = None,
        speed_bps: Optional[float] = None,
        eta_seconds: Optional[int] = None,
        error_message: Optional[str] = None,
        local_path: Optional[str] = None,
        completed: bool = False,
    ) -> None:
        """Update progress or status of a download record."""
        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status.value)
        if downloaded_bytes is not None:
            updates.append("downloaded_bytes = ?")
            params.append(downloaded_bytes)
        if total_bytes is not None:
            updates.append("total_bytes = ?")
            params.append(total_bytes)
        if progress_percent is not None:
            updates.append("progress_percent = ?")
            params.append(progress_percent)
        if speed_bps is not None:
            updates.append("speed_bps = ?")
            params.append(speed_bps)
        if eta_seconds is not None:
            updates.append("eta_seconds = ?")
            params.append(eta_seconds)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if local_path is not None:
            updates.append("local_path = ?")
            params.append(local_path)
        if completed:
            updates.append("completed_at = CURRENT_TIMESTAMP")

        if not updates:
            return

        params.append(download_id)
        query = f"UPDATE downloads SET {', '.join(updates)} WHERE id = ?"

        with self._get_connection() as conn:
            conn.execute(query, params)
            conn.commit()

    def get_downloads(
        self, status: Optional[DownloadStatus] = None, limit: int = 50
    ) -> List[DownloadRecord]:
        """Fetch list of downloads."""
        with self._get_connection() as conn:
            if status:
                cursor = conn.execute(
                    "SELECT * FROM downloads WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status.value, limit),
                )
            else:
                cursor = conn.execute("SELECT * FROM downloads ORDER BY created_at DESC LIMIT ?", (limit,))

            records = []
            for row in cursor.fetchall():
                records.append(
                    DownloadRecord(
                        id=row["id"],
                        media_id=row["media_id"],
                        media_title=row["media_title"],
                        source_type=SourceType(row["source_type"]),
                        target_url=row["target_url"],
                        local_path=row["local_path"],
                        status=DownloadStatus(row["status"]),
                        total_bytes=row["total_bytes"] or 0,
                        downloaded_bytes=row["downloaded_bytes"] or 0,
                        progress_percent=row["progress_percent"] or 0.0,
                        speed_bps=row["speed_bps"] or 0.0,
                        eta_seconds=row["eta_seconds"],
                        error_message=row["error_message"],
                        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.utcnow(),
                        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                    )
                )
            return records

    def get_download(self, download_id: int) -> Optional[DownloadRecord]:
        """Retrieve single download record by ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM downloads WHERE id = ?", (download_id,)).fetchone()
            if not row:
                return None
            return DownloadRecord(
                id=row["id"],
                media_id=row["media_id"],
                media_title=row["media_title"],
                source_type=SourceType(row["source_type"]),
                target_url=row["target_url"],
                local_path=row["local_path"],
                status=DownloadStatus(row["status"]),
                total_bytes=row["total_bytes"] or 0,
                downloaded_bytes=row["downloaded_bytes"] or 0,
                progress_percent=row["progress_percent"] or 0.0,
                speed_bps=row["speed_bps"] or 0.0,
                eta_seconds=row["eta_seconds"],
                error_message=row["error_message"],
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.utcnow(),
                completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            )

    def delete_download(self, download_id: int) -> bool:
        """Remove a download record."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
            conn.commit()
            return cursor.rowcount > 0

    # --- Addons Registry ---

    def get_addons(self, enabled_only: bool = False) -> List[AddonConfig]:
        """Fetch registered addons."""
        with self._get_connection() as conn:
            query = "SELECT * FROM addons"
            if enabled_only:
                query += " WHERE enabled = 1"
            query += " ORDER BY priority ASC"
            cursor = conn.execute(query)

            addons = []
            for row in cursor.fetchall():
                addons.append(
                    AddonConfig(
                        id=row["id"],
                        name=row["name"],
                        manifest_url=row["manifest_url"],
                        base_url=row["base_url"],
                        enabled=bool(row["enabled"]),
                        priority=row["priority"],
                        config_options=json.loads(row["config_options"] or "{}"),
                    )
                )
            return addons

    def save_addon(self, addon: AddonConfig) -> None:
        """Register or update an add-on provider."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO addons (id, name, manifest_url, base_url, enabled, priority, config_options)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    addon.id,
                    addon.name,
                    addon.manifest_url,
                    addon.base_url,
                    1 if addon.enabled else 0,
                    addon.priority,
                    json.dumps(addon.config_options),
                ),
            )
            conn.commit()

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> bool:
        """Toggle an add-on on or off."""
        with self._get_connection() as conn:
            cursor = conn.execute("UPDATE addons SET enabled = ? WHERE id = ?", (1 if enabled else 0, addon_id))
            conn.commit()
            return cursor.rowcount > 0

    def delete_addon(self, addon_id: str) -> bool:
        """Remove an add-on from the registry."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM addons WHERE id = ?", (addon_id,))
            conn.commit()
            return cursor.rowcount > 0

    # --- Bookmarks ---

    def add_bookmark(self, item: MediaItem) -> None:
        """Bookmark a movie or series for quick access."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO bookmarks (media_id, title, type, year, poster, saved_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (item.id, item.title, item.type.value, item.year, item.poster),
            )
            conn.commit()

    def remove_bookmark(self, media_id: str) -> bool:
        """Remove a bookmark."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM bookmarks WHERE media_id = ?", (media_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_bookmarks(self) -> List[Dict[str, Any]]:
        """List all bookmarks."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM bookmarks ORDER BY saved_at DESC")
            return [dict(row) for row in cursor.fetchall()]
