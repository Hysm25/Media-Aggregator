"""Asynchronous download management service with background workers and throttled progress reporting."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional
from media_aggregator.downloader.http import HTTPDownloader
from media_aggregator.downloader.manager import DEFAULT_DOWNLOAD_DIR, DownloadManager
from media_aggregator.models import DownloadRecord, DownloadStatus, SourceType, StreamSource
from media_aggregator.storage import StorageManager


class DownloadService:
    """Orchestrates async downloads, background workers, and Telegram notifications."""

    def __init__(
        self,
        storage: Optional[StorageManager] = None,
        download_dir: Optional[str | Path] = None,
    ):
        self.storage = storage or StorageManager()
        self.download_dir = Path(download_dir) if download_dir else DEFAULT_DOWNLOAD_DIR
        self.manager = DownloadManager(storage=self.storage, download_dir=self.download_dir)

        # Active downloads tracking
        self._active_tasks: Dict[int, asyncio.Task[Any]] = {}
        self._active_downloaders: Dict[int, HTTPDownloader] = {}
        self._last_progress_time: Dict[int, float] = {}

    async def recover_interrupted_downloads(self) -> int:
        """Mark any unfinished downloads from previous sessions as cancelled."""
        active = self.storage.get_downloads(status=DownloadStatus.DOWNLOADING)
        pending = self.storage.get_downloads(status=DownloadStatus.PENDING)
        interrupted = active + pending

        for rec in interrupted:
            if rec.id is not None:
                self.storage.update_download(
                    rec.id,
                    status=DownloadStatus.CANCELLED,
                    error_message="Interrupted by application restart.",
                )
        return len(interrupted)

    async def start_download(
        self,
        stream: StreamSource,
        media_id: str,
        media_title: str,
        user_id: int = 0,
        custom_filename: Optional[str] = None,
        on_progress: Optional[Callable[[DownloadRecord], Coroutine[Any, Any, None]]] = None,
        on_completed: Optional[Callable[[DownloadRecord], Coroutine[Any, Any, None]]] = None,
        on_failed: Optional[Callable[[DownloadRecord, str], Coroutine[Any, Any, None]]] = None,
    ) -> DownloadRecord:
        """Initiate download in a background task."""
        # For torrent/magnet, execution is fast (exporting .magnet and/or dispatching to client)
        if stream.is_torrent:
            rec = await asyncio.to_thread(
                self.manager.download_source,
                stream=stream,
                media_id=media_id,
                media_title=media_title,
                custom_filename=custom_filename,
                user_id=user_id,
            )
            if on_completed:
                asyncio.create_task(on_completed(rec))
            return rec

        # For HTTP streams, initialize record and run chunked transfer in background
        loop = asyncio.get_running_loop()
        clean_title = media_title.replace("/", "_")
        filename_base = custom_filename or stream.release_title or clean_title

        ext = ".mp4"
        if stream.url and ".mkv" in stream.url.lower():
            ext = ".mkv"
        elif stream.url and ".mp4" in stream.url.lower():
            ext = ".mp4"
        elif stream.inner_filename and "." in stream.inner_filename:
            ext = Path(stream.inner_filename).suffix

        dest_file = self.download_dir / f"{filename_base}{ext}"

        rec_id = self.storage.create_download(
            media_id=media_id,
            media_title=media_title,
            source_type=SourceType.HTTP,
            target_url=stream.url or "",
            local_path=str(dest_file),
            user_id=user_id,
        )
        self.storage.update_download(rec_id, status=DownloadStatus.DOWNLOADING)
        downloader = HTTPDownloader()
        self._active_downloaders[rec_id] = downloader
        self._last_progress_time[rec_id] = 0.0

        def sync_progress(downloaded: int, total: int, speed: float, eta: Optional[int]) -> None:
            pct = (downloaded / total * 100.0) if total > 0 else 0.0
            self.storage.update_download(
                rec_id,
                downloaded_bytes=downloaded,
                total_bytes=total,
                progress_percent=pct,
                speed_bps=speed,
                eta_seconds=eta,
            )

            # Throttle progress callbacks to prevent Telegram message editing rate limits (max 1 per 2 seconds)
            now = time.monotonic()
            if on_progress and (now - self._last_progress_time.get(rec_id, 0.0) >= 2.0):
                self._last_progress_time[rec_id] = now
                rec = self.storage.get_download(rec_id)
                if rec:
                    asyncio.run_coroutine_threadsafe(on_progress(rec), loop)

        async def _download_worker() -> None:
            try:
                final_path = await asyncio.to_thread(
                    downloader.download_file,
                    url=stream.url or "",
                    destination_path=dest_file,
                    progress_callback=sync_progress,
                )
                self.storage.update_download(
                    rec_id,
                    status=DownloadStatus.COMPLETED,
                    local_path=final_path,
                    completed=True,
                )
                rec = self.storage.get_download(rec_id)
                if rec and on_completed:
                    await on_completed(rec)
            except (asyncio.CancelledError, KeyboardInterrupt, InterruptedError):
                downloader.cancel()
                self.storage.update_download(
                    rec_id,
                    status=DownloadStatus.CANCELLED,
                    error_message="Download cancelled by user.",
                )
            except Exception as e:
                self.storage.update_download(
                    rec_id,
                    status=DownloadStatus.FAILED,
                    error_message=str(e),
                )
                rec = self.storage.get_download(rec_id)
                if rec and on_failed:
                    await on_failed(rec, str(e))
            finally:
                self._active_tasks.pop(rec_id, None)
                self._active_downloaders.pop(rec_id, None)
                self._last_progress_time.pop(rec_id, None)

        task = asyncio.create_task(_download_worker())
        self._active_tasks[rec_id] = task

        record = self.storage.get_download(rec_id)
        if not record:
            raise RuntimeError(f"Failed to retrieve created download record: {rec_id}")
        return record

    async def cancel_download(self, download_id: int) -> bool:
        """Cancel an ongoing download."""
        downloader = self._active_downloaders.get(download_id)
        if downloader:
            downloader.cancel()

        task = self._active_tasks.get(download_id)
        if task and not task.done():
            task.cancel()

        self.storage.update_download(
            download_id,
            status=DownloadStatus.CANCELLED,
            error_message="Cancelled by user.",
        )
        return True

    async def get_active_downloads(self, user_id: Optional[int] = None) -> List[DownloadRecord]:
        """Return currently active downloads."""
        return await asyncio.to_thread(
            self.storage.get_downloads,
            status=DownloadStatus.DOWNLOADING,
            user_id=user_id,
        )

    async def get_download_history(
        self,
        user_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[DownloadRecord]:
        """Return download history."""
        return await asyncio.to_thread(
            self.storage.get_downloads,
            status=None,
            user_id=user_id,
            limit=limit,
        )

    async def get_download(self, download_id: int) -> Optional[DownloadRecord]:
        """Retrieve a specific download record."""
        return await asyncio.to_thread(self.storage.get_download, download_id)
