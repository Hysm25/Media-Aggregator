"""Torrent handler managing Magnet export, client dispatch, and local storage."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple
from media_aggregator.magnet import dispatch_to_torrent_client, save_magnet_file


class TorrentDownloader:
    """Dispatches or exports torrent sources and magnet links."""

    @staticmethod
    def export_magnet_file(magnet_uri: str, output_path: str | Path) -> str:
        """Save a Magnet URI to a local .magnet file."""
        return save_magnet_file(magnet_uri, str(output_path))

    @staticmethod
    def dispatch(magnet_uri: str, client: Optional[str] = None) -> Tuple[bool, str]:
        """Dispatch magnet URI to an installed BitTorrent client."""
        return dispatch_to_torrent_client(magnet_uri, client=client)
