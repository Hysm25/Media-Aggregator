"""Data models for Media Source Aggregator."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MediaType(str, enum.Enum):
    MOVIE = "movie"
    SERIES = "series"
    ANIME = "anime"
    CHANNEL = "channel"
    OTHER = "other"


class SourceType(str, enum.Enum):
    TORRENT = "torrent"
    HTTP = "http"
    DEBRID = "debrid"
    LIVE = "live"
    UNKNOWN = "unknown"


class Quality(str, enum.Enum):
    UHD_4K = "4K"
    FHD_1080P = "1080p"
    HD_720P = "720p"
    SD_480P = "480p"
    CAM_SCR = "CAM/SCR"
    UNKNOWN = "Unknown"

    @property
    def score(self) -> int:
        """Numeric score for quality comparisons."""
        scores = {
            Quality.UHD_4K: 400,
            Quality.FHD_1080P: 300,
            Quality.HD_720P: 200,
            Quality.SD_480P: 100,
            Quality.UNKNOWN: 50,
            Quality.CAM_SCR: 10,
        }
        return scores.get(self, 0)


class DownloadStatus(str, enum.Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EpisodeItem(BaseModel):
    """Represents a single TV series episode."""
    id: str  # e.g., 'tt0903747:1:1'
    season: int = 1
    episode: int = 1
    title: str = "Episode"
    overview: Optional[str] = None
    released: Optional[str] = None
    thumbnail: Optional[str] = None
    rating: Optional[str] = None


class MediaItem(BaseModel):
    """Represents a movie or series discovery item."""
    id: str  # e.g., 'tt1234567' or custom
    title: str
    type: MediaType = MediaType.MOVIE
    year: Optional[str] = None
    poster: Optional[str] = None
    background: Optional[str] = None
    synopsis: Optional[str] = None
    genres: List[str] = Field(default_factory=list)
    cast: List[str] = Field(default_factory=list)
    director: Optional[str] = None
    imdb_rating: Optional[str] = None
    runtime: Optional[str] = None
    episodes: List[EpisodeItem] = Field(default_factory=list)

    @property
    def display_year(self) -> str:
        return self.year if self.year else "N/A"


class StreamSource(BaseModel):
    """Represents an aggregated stream/download source."""
    id: str
    provider: str
    name: str = ""
    title: str = ""
    release_title: str = ""
    inner_filename: Optional[str] = None
    info_hash: Optional[str] = None
    file_idx: Optional[int] = None
    url: Optional[str] = None
    quality: Quality = Quality.UNKNOWN
    resolution: str = "Unknown"
    source_type: SourceType = SourceType.TORRENT
    seeders: Optional[int] = None
    size_bytes: Optional[int] = None
    size_display: Optional[str] = None
    indexer: Optional[str] = None
    codecs: List[str] = Field(default_factory=list)
    audio: List[str] = Field(default_factory=list)
    hdr: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    behavior_hints: Dict[str, Any] = Field(default_factory=dict)
    trackers: List[str] = Field(default_factory=list)
    is_debrid: bool = False

    @property
    def is_torrent(self) -> bool:
        return bool(self.info_hash)

    @property
    def is_http(self) -> bool:
        return bool(self.url and (self.url.startswith("http://") or self.url.startswith("https://")))

    def build_magnet_uri(self, custom_trackers: Optional[List[str]] = None) -> Optional[str]:
        """Construct RFC-compliant Magnet URI from infoHash."""
        if not self.info_hash:
            return None
        from media_aggregator.magnet import build_magnet_link
        trackers = custom_trackers or self.trackers
        return build_magnet_link(
            info_hash=self.info_hash,
            display_name=self.release_title or self.title,
            trackers=trackers,
            file_idx=self.file_idx,
        )


class DownloadRecord(BaseModel):
    """Represents a local download history record."""
    id: Optional[int] = None
    media_id: str
    media_title: str
    source_type: SourceType = SourceType.HTTP
    target_url: str
    local_path: Optional[str] = None
    status: DownloadStatus = DownloadStatus.PENDING
    total_bytes: int = 0
    downloaded_bytes: int = 0
    progress_percent: float = 0.0
    speed_bps: float = 0.0
    eta_seconds: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class AddonManifest(BaseModel):
    """Manifest describing a Stremio Add-on."""
    id: str
    name: str
    version: str = "1.0.0"
    description: Optional[str] = None
    resources: List[Any] = Field(default_factory=list)
    types: List[str] = Field(default_factory=list)
    catalogs: List[Dict[str, Any]] = Field(default_factory=list)
    id_prefixes: List[str] = Field(default_factory=list)
    icon: Optional[str] = None
    background: Optional[str] = None


class AddonConfig(BaseModel):
    """Saved configuration for an add-on provider."""
    id: str
    name: str
    manifest_url: str
    base_url: str
    enabled: bool = True
    priority: int = 10
    config_options: Dict[str, Any] = Field(default_factory=dict)
