"""SQLite-backed persistent storage for history, media cache, addons, and downloads."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from datetime import datetime, timezone
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
    UserRecord,
    UserSettings,
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
                    user_id INTEGER DEFAULT 0,
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
                    user_id INTEGER DEFAULT 0,
                    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Users table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    is_admin INTEGER DEFAULT 0,
                    is_allowed INTEGER DEFAULT 0,
                    settings_json TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Schema migrations for existing databases
            cursor.execute("PRAGMA table_info(downloads)")
            columns_dl = [row["name"] for row in cursor.fetchall()]
            if "user_id" not in columns_dl:
                cursor.execute("ALTER TABLE downloads ADD COLUMN user_id INTEGER DEFAULT 0")

            cursor.execute("PRAGMA table_info(bookmarks)")
            columns_bm = [row["name"] for row in cursor.fetchall()]
            if "user_id" not in columns_bm:
                cursor.execute("ALTER TABLE bookmarks ADD COLUMN user_id INTEGER DEFAULT 0")

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
                        json.dumps({"resources": ["catalog", "meta", "addon_catalog"]}),
                    ),
                    (
                        "com.stremio.torrentio.addon",
                        "Torrentio (Scraper)",
                        "https://torrentio.strem.fun/manifest.json",
                        "https://torrentio.strem.fun",
                        1,
                        5,
                        json.dumps({"resources": ["stream"]}),
                    ),
                    (
                        "anime-kitsu",
                        "Anime Kitsu (Anime Catalog & Subtitles)",
                        "https://anime-kitsu.strem.fun/manifest.json",
                        "https://anime-kitsu.strem.fun",
                        1,
                        10,
                        json.dumps({"resources": ["catalog", "meta", "subtitles"]}),
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
        user_id: int = 0,
    ) -> int:
        """Create a new download record."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO downloads (
                    user_id, media_id, media_title, source_type, target_url, local_path, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (user_id, media_id, media_title, source_type.value, target_url, local_path, DownloadStatus.PENDING.value),
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
        self,
        status: Optional[DownloadStatus] = None,
        user_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[DownloadRecord]:
        """Fetch list of downloads."""
        with self._get_connection() as conn:
            query = "SELECT * FROM downloads"
            conditions = []
            params = []
            if status:
                conditions.append("status = ?")
                params.append(status.value)
            if user_id is not None:
                conditions.append("user_id = ?")
                params.append(user_id)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, params)
            records = []
            for row in cursor.fetchall():
                row_dict = dict(row)
                records.append(
                    DownloadRecord(
                        id=row_dict["id"],
                        user_id=row_dict.get("user_id") or 0,
                        media_id=row_dict["media_id"],
                        media_title=row_dict["media_title"],
                        source_type=SourceType(row_dict["source_type"]),
                        target_url=row_dict["target_url"],
                        local_path=row_dict["local_path"],
                        status=DownloadStatus(row_dict["status"]),
                        total_bytes=row_dict["total_bytes"] or 0,
                        downloaded_bytes=row_dict["downloaded_bytes"] or 0,
                        progress_percent=row_dict["progress_percent"] or 0.0,
                        speed_bps=row_dict["speed_bps"] or 0.0,
                        eta_seconds=row_dict["eta_seconds"],
                        error_message=row_dict["error_message"],
                        created_at=datetime.fromisoformat(row_dict["created_at"]) if row_dict["created_at"] else datetime.now(timezone.utc),
                        completed_at=datetime.fromisoformat(row_dict["completed_at"]) if row_dict["completed_at"] else None,
                    )
                )
            return records

    def get_download(self, download_id: int) -> Optional[DownloadRecord]:
        """Retrieve single download record by ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM downloads WHERE id = ?", (download_id,)).fetchone()
            if not row:
                return None
            row_dict = dict(row)
            return DownloadRecord(
                id=row_dict["id"],
                user_id=row_dict.get("user_id") or 0,
                media_id=row_dict["media_id"],
                media_title=row_dict["media_title"],
                source_type=SourceType(row_dict["source_type"]),
                target_url=row_dict["target_url"],
                local_path=row_dict["local_path"],
                status=DownloadStatus(row_dict["status"]),
                total_bytes=row_dict["total_bytes"] or 0,
                downloaded_bytes=row_dict["downloaded_bytes"] or 0,
                progress_percent=row_dict["progress_percent"] or 0.0,
                speed_bps=row_dict["speed_bps"] or 0.0,
                eta_seconds=row_dict["eta_seconds"],
                error_message=row_dict["error_message"],
                created_at=datetime.fromisoformat(row_dict["created_at"]) if row_dict["created_at"] else datetime.now(timezone.utc),
                completed_at=datetime.fromisoformat(row_dict["completed_at"]) if row_dict["completed_at"] else None,
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

    def add_bookmark(self, item: MediaItem, user_id: int = 0) -> None:
        """Bookmark a movie or series for quick access."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO bookmarks (media_id, title, type, year, poster, user_id, saved_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (item.id, item.title, item.type.value, item.year, item.poster, user_id),
            )
            conn.commit()

    def remove_bookmark(self, media_id: str, user_id: Optional[int] = None) -> bool:
        """Remove a bookmark."""
        with self._get_connection() as conn:
            if user_id is not None:
                cursor = conn.execute("DELETE FROM bookmarks WHERE media_id = ? AND user_id = ?", (media_id, user_id))
            else:
                cursor = conn.execute("DELETE FROM bookmarks WHERE media_id = ?", (media_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_bookmarks(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """List bookmarks."""
        with self._get_connection() as conn:
            if user_id is not None:
                cursor = conn.execute("SELECT * FROM bookmarks WHERE user_id = ? ORDER BY saved_at DESC", (user_id,))
            else:
                cursor = conn.execute("SELECT * FROM bookmarks ORDER BY saved_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    # --- User Management ---

    def get_or_create_user(
        self,
        user_id: int,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
        is_admin: bool = False,
        is_allowed: bool = False,
    ) -> UserRecord:
        """Retrieve existing user or register a new user."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                # Update username, full_name, and last_active_at if changed
                conn.execute(
                    """
                    UPDATE users
                    SET username = COALESCE(?, username),
                        full_name = COALESCE(?, full_name),
                        last_active_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                    """,
                    (username, full_name, user_id),
                )
                conn.commit()
                updated_row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
                return self._row_to_user(updated_row)

            # Insert new user
            settings = UserSettings()
            conn.execute(
                """
                INSERT INTO users (user_id, username, full_name, is_admin, is_allowed, settings_json, created_at, last_active_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    user_id,
                    username,
                    full_name,
                    1 if is_admin else 0,
                    1 if is_allowed else 0,
                    settings.model_dump_json(),
                ),
            )
            conn.commit()
            new_row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return self._row_to_user(new_row)

    def get_user(self, user_id: int) -> Optional[UserRecord]:
        """Fetch a user record by user_id."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                return None
            return self._row_to_user(row)

    def update_user_activity(self, user_id: int) -> None:
        """Update last_active_at timestamp for user."""
        with self._get_connection() as conn:
            conn.execute("UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
            conn.commit()

    def update_user_settings(self, user_id: int, settings: UserSettings | Dict[str, Any]) -> None:
        """Update user preferences."""
        if isinstance(settings, UserSettings):
            settings_json = settings.model_dump_json()
        else:
            settings_json = json.dumps(settings)

        with self._get_connection() as conn:
            conn.execute("UPDATE users SET settings_json = ? WHERE user_id = ?", (settings_json, user_id))
            conn.commit()

    def set_user_allowed(self, user_id: int, is_allowed: bool) -> bool:
        """Authorize or revoke user access."""
        with self._get_connection() as conn:
            cursor = conn.execute("UPDATE users SET is_allowed = ? WHERE user_id = ?", (1 if is_allowed else 0, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def set_user_admin(self, user_id: int, is_admin: bool) -> bool:
        """Promote or demote user admin status."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE users SET is_admin = ?, is_allowed = CASE WHEN ? = 1 THEN 1 ELSE is_allowed END WHERE user_id = ?",
                (1 if is_admin else 0, 1 if is_admin else 0, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_users(self, allowed_only: bool = False) -> List[UserRecord]:
        """List registered users."""
        with self._get_connection() as conn:
            query = "SELECT * FROM users"
            if allowed_only:
                query += " WHERE is_allowed = 1"
            query += " ORDER BY created_at DESC"
            cursor = conn.execute(query)
            return [self._row_to_user(row) for row in cursor.fetchall()]

    def count_admins(self) -> int:
        """Count how many users currently have is_admin = 1."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) as count FROM users WHERE is_admin = 1")
            return cursor.fetchone()["count"]

    def get_system_stats(self) -> Dict[str, Any]:
        """Return system statistics for admin dashboard."""
        with self._get_connection() as conn:
            cached_media = conn.execute("SELECT COUNT(*) as c FROM media_cache").fetchone()["c"]
            discovered_streams = conn.execute("SELECT COUNT(*) as c FROM stream_history").fetchone()["c"]
            total_downloads = conn.execute("SELECT COUNT(*) as c FROM downloads").fetchone()["c"]
            active_downloads = conn.execute(
                "SELECT COUNT(*) as c FROM downloads WHERE status = ?",
                (DownloadStatus.DOWNLOADING.value,),
            ).fetchone()["c"]
            completed_downloads = conn.execute(
                "SELECT COUNT(*) as c FROM downloads WHERE status = ?",
                (DownloadStatus.COMPLETED.value,),
            ).fetchone()["c"]
            failed_downloads = conn.execute(
                "SELECT COUNT(*) as c FROM downloads WHERE status = ?",
                (DownloadStatus.FAILED.value,),
            ).fetchone()["c"]
            total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
            allowed_users = conn.execute("SELECT COUNT(*) as c FROM users WHERE is_allowed = 1").fetchone()["c"]
            active_addons = conn.execute("SELECT COUNT(*) as c FROM addons WHERE enabled = 1").fetchone()["c"]

            return {
                "cached_media": cached_media,
                "discovered_streams": discovered_streams,
                "total_downloads": total_downloads,
                "active_downloads": active_downloads,
                "completed_downloads": completed_downloads,
                "failed_downloads": failed_downloads,
                "total_users": total_users,
                "allowed_users": allowed_users,
                "active_addons": active_addons,
            }

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> UserRecord:
        """Convert a database row to a UserRecord."""
        raw_settings = json.loads(row["settings_json"] or "{}")
        settings = UserSettings(**raw_settings)
        return UserRecord(
            user_id=row["user_id"],
            username=row["username"],
            full_name=row["full_name"],
            is_admin=bool(row["is_admin"]),
            is_allowed=bool(row["is_allowed"]),
            settings=settings,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(timezone.utc),
            last_active_at=datetime.fromisoformat(row["last_active_at"]) if row["last_active_at"] else datetime.now(timezone.utc),
        )
