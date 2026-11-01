"""Tests for Click CLI commands."""

from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner
from media_aggregator.cli.main import cli
from media_aggregator.models import MediaItem, MediaType, Quality, StreamSource


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Media Source Aggregator" in result.output
    assert "search" in result.output
    assert "streams" in result.output


def test_cli_search(runner):
    mock_items = [
        MediaItem(id="tt1375666", title="Inception", type=MediaType.MOVIE, year="2010", imdb_rating="8.8"),
    ]

    with patch("media_aggregator.providers.cinemeta.CinemetaProvider.search", return_value=mock_items):
        result = runner.invoke(cli, ["search", "Inception"])
        assert result.exit_code == 0
        assert "Inception" in result.output
        assert "tt1375666" in result.output


def test_cli_info(runner):
    mock_item = MediaItem(
        id="tt1375666",
        title="Inception",
        type=MediaType.MOVIE,
        year="2010",
        imdb_rating="8.8",
        director="Christopher Nolan",
        synopsis="A thief who steals corporate secrets through the use of dream-sharing technology...",
    )

    with patch("media_aggregator.providers.cinemeta.CinemetaProvider.get_metadata", return_value=mock_item):
        result = runner.invoke(cli, ["info", "tt1375666"])
        assert result.exit_code == 0
        assert "Christopher Nolan" in result.output
        assert "Inception" in result.output


def test_cli_streams(runner):
    mock_stream = StreamSource(
        id="s1",
        provider="Torrentio",
        name="Torrentio\n1080p",
        title="Inception.2010.1080p.BluRay\n👤 85 💾 2.1 GB ⚙️ RARBG",
        release_title="Inception.2010.1080p.BluRay",
        info_hash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
        quality=Quality.FHD_1080P,
        resolution="1080p",
        seeders=85,
        size_display="2.1 GB",
    )

    with patch("media_aggregator.aggregator.StreamAggregator.aggregate_streams", return_value=[mock_stream]):
        result = runner.invoke(cli, ["streams", "tt1375666"])
        assert result.exit_code == 0
        assert "Torrentio" in result.output
        assert "1080p" in result.output

        # Also test json output
        json_res = runner.invoke(cli, ["streams", "tt1375666", "--json-out"])
        assert json_res.exit_code == 0
        assert "Inception.2010.1080p.BluRay" in json_res.output


def test_cli_magnet(runner):
    mock_stream = StreamSource(
        id="s1",
        provider="Torrentio",
        release_title="Inception.2010.1080p.BluRay",
        info_hash="da39a3ee5e6b4b0d3255bfef95601890afd80709",
        quality=Quality.FHD_1080P,
        resolution="1080p",
    )

    with patch("media_aggregator.aggregator.StreamAggregator.aggregate_streams", return_value=[mock_stream]):
        result = runner.invoke(cli, ["magnet", "tt1375666"])
        assert result.exit_code == 0
        assert "magnet:?xt=urn%3Abtih%3Ada39a3ee5e6b4b0d3255bfef95601890afd80709" in result.output


def test_cli_addons(runner, tmp_path):
    env = {"MEDIA_AGGREGATOR_DB": str(tmp_path / "cli_test.db")}
    result = runner.invoke(cli, ["addons", "list"], env=env)
    assert result.exit_code == 0
    assert "Cinemeta" in result.output
    assert "Torrentio" in result.output
