"""Tests for providers subsystem (Cinemeta, Torrentio, Generic, Registry)."""

from unittest.mock import MagicMock, patch
import pytest
from media_aggregator.models import MediaType
from media_aggregator.providers.cinemeta import CinemetaProvider
from media_aggregator.providers.generic import GenericStremioProvider
from media_aggregator.providers.registry import ProviderRegistry
from media_aggregator.providers.torrentio import TorrentioProvider
from media_aggregator.storage import StorageManager


def test_cinemeta_provider_parsing():
    provider = CinemetaProvider()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "metas": [
            {
                "id": "tt1375666",
                "name": "Inception",
                "type": "movie",
                "year": "2010",
                "genres": ["Action", "Sci-Fi"],
                "imdbRating": "8.8",
            }
        ]
    }

    with patch.object(provider.session, "get", return_value=mock_resp):
        results = provider.search("Inception", MediaType.MOVIE)
        assert len(results) == 1
        item = results[0]
        assert item.id == "tt1375666"
        assert item.title == "Inception"
        assert item.year == "2010"
        assert item.imdb_rating == "8.8"


def test_cinemeta_series_episodes_parsing():
    provider = CinemetaProvider()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "meta": {
            "id": "tt0903747",
            "name": "Breaking Bad",
            "type": "series",
            "year": "2008",
            "videos": [
                {
                    "id": "tt0903747:1:1",
                    "season": 1,
                    "number": 1,
                    "name": "Pilot",
                    "released": "2008-01-20T00:00:00.000Z",
                    "overview": "A chemistry teacher diagnosed with lung cancer...",
                },
                {
                    "id": "tt0903747:1:2",
                    "season": 1,
                    "number": 2,
                    "name": "Cat's in the Bag...",
                    "released": "2008-01-27T00:00:00.000Z",
                },
            ],
        }
    }

    with patch.object(provider.session, "get", return_value=mock_resp):
        item = provider.get_metadata(MediaType.SERIES, "tt0903747")
        assert item is not None
        assert item.title == "Breaking Bad"
        assert len(item.episodes) == 2
        assert item.episodes[0].title == "Pilot"
        assert item.episodes[0].season == 1
        assert item.episodes[0].episode == 1
        assert item.episodes[1].id == "tt0903747:1:2"


def test_torrentio_config_path_builder():
    provider = TorrentioProvider(
        providers=["yts", "1337x"],
        sort="seeders",
        quality_filter=["cam", "scr"],
        limit=5,
        debrid_provider="realdebrid",
        debrid_api_key="MY_KEY",
    )

    config_path = provider.build_config_path()
    assert "providers=yts,1337x" in config_path
    assert "sort=seeders" in config_path
    assert "qualityfilter=cam,scr" in config_path
    assert "limit=5" in config_path
    assert "realdebrid=MY_KEY" in config_path

    effective_url = provider.get_effective_base_url()
    assert config_path in effective_url


def test_torrentio_streams_fetching():
    provider = TorrentioProvider()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "streams": [
            {
                "name": "Torrentio\n1080p",
                "title": "Inception.2010.1080p.BluRay.x264\n👤 150 💾 2.1 GB ⚙️ RARBG",
                "infoHash": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
                "fileIdx": 0,
            }
        ]
    }

    with patch.object(provider.session, "get", return_value=mock_resp):
        streams = provider.get_streams(MediaType.MOVIE, "tt1375666")
        assert len(streams) == 1
        s = streams[0]
        assert s.provider == "Torrentio"
        assert s.info_hash == "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        assert s.seeders == 150
        assert s.size_display == "2.1 GB"
        assert s.indexer == "RARBG"


def test_generic_stremio_provider():
    provider = GenericStremioProvider(name="CyberFlix", base_url="https://cyberflix.catalog")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "streams": [
            {
                "name": "Direct Stream",
                "title": "Direct.1080p.Stream",
                "url": "https://stream.server.org/video.mp4",
            }
        ]
    }

    with patch.object(provider.session, "get", return_value=mock_resp):
        streams = provider.get_streams(MediaType.MOVIE, "tt1234567")
        assert len(streams) == 1
        assert streams[0].url == "https://stream.server.org/video.mp4"
        assert streams[0].is_http is True


def test_provider_registry(tmp_path):
    storage = StorageManager(db_path=tmp_path / "test.db")
    registry = ProviderRegistry(storage=storage)

    active = registry.get_active_providers()
    assert len(active) >= 2

    discovery = registry.get_discovery_provider()
    assert isinstance(discovery, CinemetaProvider)

    stream_providers = registry.get_stream_providers()
    assert any(isinstance(p, TorrentioProvider) for p in stream_providers)
