"""Downloader engine supporting HTTP chunked range transfers and Magnet link export."""

from media_aggregator.downloader.http import HTTPDownloader
from media_aggregator.downloader.manager import DownloadManager
from media_aggregator.downloader.torrent import TorrentDownloader

__all__ = ["HTTPDownloader", "TorrentDownloader", "DownloadManager"]
