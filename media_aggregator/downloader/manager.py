"""Unified download orchestrator managing HTTP streams, Magnet links, and history."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional
from media_aggregator.downloader.http import HTTPDownloader
from media_aggregator.downloader.torrent import TorrentDownloader
from media_aggregator.models import (
    DownloadRecord,
    DownloadStatus,
    SourceType,
    StreamSource,
)
from media_aggregator.storage import StorageManager

DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "MediaAggregator"


def sanitize_filename(name: str) -> str:
    """Sanitize string to be safe for filenames across operating systems."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", name)
    return cleaned.strip(". ")


class DownloadManager:
    """Coordinates media downloads, status tracking, and persistent history."""

    def __init__(
        self,
        storage: Optional[StorageManager] = None,
        download_dir: Optional[str | Path] = None,
    ):
        self.storage = storage or StorageManager()
        self.download_dir = Path(download_dir) if download_dir else DEFAULT_DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.http_downloader = HTTPDownloader()

    def download_source(
        self,
        stream: StreamSource,
        media_id: str,
        media_title: str,
        progress_callback: Optional[Callable[[DownloadRecord], None]] = None,
        custom_filename: Optional[str] = None,
    ) -> DownloadRecord:
        """Download or dispatch an aggregated stream source."""
        clean_title = sanitize_filename(media_title)
        filename_base = sanitize_filename(custom_filename or stream.release_title or clean_title)

        if stream.is_http and stream.url:
            # Direct HTTP Download
            # Determine extension
            ext = ".mp4"
            if ".mkv" in stream.url.lower():
                ext = ".mkv"
            elif ".mp4" in stream.url.lower():
                ext = ".mp4"
            elif stream.inner_filename and "." in stream.inner_filename:
                ext = Path(stream.inner_filename).suffix

            dest_file = self.download_dir / f"{filename_base}{ext}"

            rec_id = self.storage.create_download(
                media_id=media_id,
                media_title=media_title,
                source_type=SourceType.HTTP,
                target_url=stream.url,
                local_path=str(dest_file),
            )
            self.storage.update_download(rec_id, status=DownloadStatus.DOWNLOADING)

            def internal_progress(downloaded: int, total: int, speed: float, eta: Optional[int]) -> None:
                pct = (downloaded / total * 100.0) if total > 0 else 0.0
                self.storage.update_download(
                    rec_id,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    progress_percent=pct,
                    speed_bps=speed,
                    eta_seconds=eta,
                )
                if progress_callback:
                    rec = self.storage.get_download(rec_id)
                    if rec:
                        progress_callback(rec)

            try:
                final_path = self.http_downloader.download_file(
                    url=stream.url,
                    destination_path=dest_file,
                    progress_callback=internal_progress,
                )
                self.storage.update_download(
                    rec_id,
                    status=DownloadStatus.COMPLETED,
                    local_path=final_path,
                    completed=True,
                )
            except (KeyboardInterrupt, InterruptedError):
                self.storage.update_download(
                    rec_id,
                    status=DownloadStatus.CANCELLED,
                    error_message="Download was cancelled by user.",
                )
                raise
            except Exception as e:
                self.storage.update_download(
                    rec_id,
                    status=DownloadStatus.FAILED,
                    error_message=str(e),
                )
                raise e

            return self.storage.get_download(rec_id)  # type: ignore

        elif stream.is_torrent and stream.info_hash:
            # BitTorrent / Magnet handling
            magnet_uri = stream.build_magnet_uri()
            if not magnet_uri:
                raise ValueError("Could not construct Magnet URI from stream.")

            magnet_file = self.download_dir / f"{filename_base}.magnet"
            TorrentDownloader.export_magnet_file(magnet_uri, magnet_file)

            rec_id = self.storage.create_download(
                media_id=media_id,
                media_title=media_title,
                source_type=SourceType.TORRENT,
                target_url=magnet_uri,
                local_path=str(magnet_file),
            )

            # Try to dispatch to client if available
            dispatched, msg = TorrentDownloader.dispatch(magnet_uri)
            # If dispatched to an active downloader daemon (aria2c or transmission), status is DOWNLOADING.
            # If exported as magnet or dispatched to generic launcher (xdg-open), status is COMPLETED.
            if dispatched and any(d in msg for d in ["aria2c", "transmission-daemon"]):
                self.storage.update_download(
                    rec_id,
                    status=DownloadStatus.DOWNLOADING,
                    error_message=msg,
                )
            else:
                self.storage.update_download(
                    rec_id,
                    status=DownloadStatus.COMPLETED,
                    error_message=f"Magnet file exported. {msg}",
                    completed=True,
                )

            return self.storage.get_download(rec_id)  # type: ignore

        else:
            raise ValueError(f"Unsupported stream source type: {stream.source_type}")

    def list_history(
        self,
        status: Optional[DownloadStatus] = None,
        limit: int = 50,
    ) -> List[DownloadRecord]:
        """Get past download records."""
        return self.storage.get_downloads(status=status, limit=limit)
