"""Resilient HTTP media downloader supporting chunked streaming, range resumes, and verification."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional
import requests

CHUNK_SIZE = 64 * 1024  # 64 KB chunks


class HTTPDownloader:
    """HTTP/HTTPS media file downloader with byte-range resume and verification."""

    def __init__(self, session: Optional[requests.Session] = None, timeout: float = 15.0):
        self.session = session or requests.Session()
        self.timeout = timeout
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Signal the download to cancel."""
        self._cancel_event.set()

    def download_file(
        self,
        url: str,
        destination_path: str | Path,
        progress_callback: Optional[Callable[[int, int, float, Optional[int]], None]] = None,
        expected_sha256: Optional[str] = None,
    ) -> str:
        """Download a file with resume support.
        
        Args:
            url: Direct HTTP/HTTPS media source URL.
            destination_path: Local path to write to.
            progress_callback: Callable accepting (downloaded_bytes, total_bytes, speed_bps, eta_seconds).
            expected_sha256: Optional SHA-256 hash to verify upon completion.
            
        Returns:
            Resolved absolute path of the downloaded file.
        """
        dest = Path(destination_path).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        part_path = dest.with_name(f"{dest.name}.part")

        # Reset cancel flag at start of new download
        self._cancel_event.clear()

        downloaded_bytes = 0
        if part_path.exists():
            downloaded_bytes = part_path.stat().st_size

        headers = {
            "User-Agent": "MediaSourceAggregator/1.0.0",
        }
        if downloaded_bytes > 0:
            headers["Range"] = f"bytes={downloaded_bytes}-"

        try:
            response = self.session.get(url, headers=headers, stream=True, timeout=self.timeout)
        except requests.RequestException as e:
            raise ConnectionError(f"Network error while connecting to {url}: {e}") from e

        # Check for range satisfaction or fresh download
        if response.status_code == 416:
            # Range not satisfiable. Check if part file is already complete and valid
            is_valid_complete = False
            if part_path.exists():
                if expected_sha256:
                    hasher = hashlib.sha256()
                    with open(part_path, "rb") as f:
                        while chunk := f.read(128 * 1024):
                            hasher.update(chunk)
                    if hasher.hexdigest().lower() == expected_sha256.lower():
                        is_valid_complete = True
                else:
                    # Check Content-Range header if provided: bytes */total
                    cr = response.headers.get("Content-Range", "")
                    if "/" in cr:
                        total_str = cr.split("/")[-1].strip()
                        if total_str.isdigit() and int(total_str) == part_path.stat().st_size:
                            is_valid_complete = True

            if is_valid_complete:
                part_path.rename(dest)
                return str(dest)

            # Otherwise, the partial file is corrupted/stale; remove and restart from 0
            if part_path.exists():
                part_path.unlink()
            downloaded_bytes = 0
            try:
                response = self.session.get(url, stream=True, timeout=self.timeout)
            except requests.RequestException as e:
                raise ConnectionError(f"Network error while restarting download from {url}: {e}") from e

        if response.status_code not in (200, 206):
            raise requests.HTTPError(
                f"Download failed with HTTP {response.status_code}: {response.text[:200]}",
                response=response,
            )

        content_length_header = response.headers.get("Content-Length")
        if response.status_code == 206:
            # Partial content
            content_range = response.headers.get("Content-Range", "")
            if "/" in content_range:
                total_bytes = int(content_range.split("/")[-1])
            elif content_length_header:
                total_bytes = downloaded_bytes + int(content_length_header)
            else:
                total_bytes = downloaded_bytes
            file_mode = "ab"
        else:
            # Full content (server does not support range or fresh start)
            downloaded_bytes = 0
            total_bytes = int(content_length_header) if content_length_header else 0
            file_mode = "wb"

        start_time = time.time()
        last_calc_time = start_time
        bytes_since_last_calc = 0
        speed_bps = 0.0

        with open(part_path, file_mode) as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if self._cancel_event.is_set():
                    raise InterruptedError("Download was cancelled by user.")

                if chunk:
                    f.write(chunk)
                    chunk_len = len(chunk)
                    downloaded_bytes += chunk_len
                    bytes_since_last_calc += chunk_len

                    now = time.time()
                    elapsed_calc = now - last_calc_time
                    if elapsed_calc >= 0.5:
                        speed_bps = bytes_since_last_calc / elapsed_calc
                        bytes_since_last_calc = 0
                        last_calc_time = now

                        eta = int((total_bytes - downloaded_bytes) / speed_bps) if speed_bps > 0 and total_bytes > downloaded_bytes else None
                        if progress_callback:
                            progress_callback(downloaded_bytes, total_bytes, speed_bps, eta)

        # Final progress report
        total_elapsed = time.time() - start_time
        final_speed = (downloaded_bytes / total_elapsed) if total_elapsed > 0 else speed_bps
        if progress_callback:
            progress_callback(downloaded_bytes, total_bytes, final_speed, 0)

        # Move partial file to destination
        if dest.exists():
            dest.unlink()
        part_path.rename(dest)

        # Verify SHA-256 if requested
        if expected_sha256:
            hasher = hashlib.sha256()
            with open(dest, "rb") as f:
                while chunk := f.read(128 * 1024):
                    hasher.update(chunk)
            computed = hasher.hexdigest().lower()
            if computed != expected_sha256.lower():
                raise ValueError(f"Checksum mismatch: expected {expected_sha256}, got {computed}")

        return str(dest)
