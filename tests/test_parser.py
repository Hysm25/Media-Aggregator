"""Tests for stream parser and title/quality/codec extractors."""

import pytest
from media_aggregator.models import Quality, SourceType
from media_aggregator.parser import (
    extract_audio,
    extract_codecs,
    extract_hdr,
    extract_resolution_and_quality,
    parse_generic_stream,
    parse_size_to_bytes,
    parse_torrentio_stream,
)


def test_parse_size_to_bytes():
    assert parse_size_to_bytes("10.31 GB") == int(10.31 * 1000**3)
    assert parse_size_to_bytes("500 MB") == int(500 * 1000**2)
    assert parse_size_to_bytes("2.5 GiB") == int(2.5 * 1024**3)
    assert parse_size_to_bytes("100 KB") == int(100 * 1000)
    assert parse_size_to_bytes("invalid") is None
    assert parse_size_to_bytes("") is None
    assert parse_size_to_bytes(None) is None


def test_extract_resolution_and_quality():
    res, qual = extract_resolution_and_quality("Big.Hero.6.2014.2160p.UHD.BluRay")
    assert res == "4K (2160p)"
    assert qual == Quality.UHD_4K

    res, qual = extract_resolution_and_quality("Avatar.1080p.WEBRip.x264")
    assert res == "1080p"
    assert qual == Quality.FHD_1080P

    res, qual = extract_resolution_and_quality("Breaking.Bad.S01E01.720p.HDTV")
    assert res == "720p"
    assert qual == Quality.HD_720P

    res, qual = extract_resolution_and_quality("Classic.Movie.480p.DVDRip")
    assert res == "480p"
    assert qual == Quality.SD_480P

    res, qual = extract_resolution_and_quality("Leaked.New.Release.HDCAM.x264")
    assert res == "CAM/SCR"
    assert qual == Quality.CAM_SCR

    res, qual = extract_resolution_and_quality("Some.Indie.Film.Without.Res")
    assert res == "Unknown"
    assert qual == Quality.UNKNOWN


def test_extract_codecs():
    codecs = extract_codecs("Movie.2024.2160p.HEVC.10bit.x265.mkv")
    assert "HEVC/x265" in codecs

    codecs = extract_codecs("Movie.2024.1080p.x264.AVC.mp4")
    assert "AVC/x264" in codecs

    codecs = extract_codecs("Movie.2024.AV1.HDR.mkv")
    assert "AV1" in codecs

    codecs = extract_codecs("Old.Film.XviD.avi")
    assert "XviD" in codecs


def test_extract_hdr():
    hdr = extract_hdr("Movie.2024.2160p.DV.HDR10+.10bit.mkv")
    assert "Dolby Vision" in hdr
    assert "HDR10+" in hdr
    assert "10-bit" in hdr

    hdr2 = extract_hdr("Movie.HDR10.x265")
    assert "HDR10" in hdr2


def test_extract_audio():
    audio = extract_audio("Movie.2160p.TrueHD.Atmos.7.1.x265")
    assert "Dolby Atmos" in audio
    assert "TrueHD" in audio
    assert "7.1" in audio

    audio2 = extract_audio("Movie.1080p.DTS-HD.MA.5.1.AC3")
    assert "DTS-HD MA" in audio2
    assert "5.1" in audio2
    assert "AC3" in audio2


def test_parse_torrentio_stream():
    sample = {
        "name": "Torrentio\n4k HDR",
        "title": "Big Hero 6 (2014) (2160p BluRay x265 HEVC 10bit HDR AAC 7.1 Tigole) [QxR]\n👤 40 💾 5 GB ⚙️ 1337x",
        "infoHash": "3c86b78efa012a402c28712d8be282d813f1a279",
        "fileIdx": 1,
        "behaviorHints": {"bingeGroup": "torrentio|4k|hdr"},
    }

    stream = parse_torrentio_stream(sample, provider_name="Torrentio")
    assert stream.provider == "Torrentio"
    assert stream.info_hash == "3c86b78efa012a402c28712d8be282d813f1a279"
    assert stream.file_idx == 1
    assert stream.quality == Quality.UHD_4K
    assert stream.resolution == "4K (2160p)"
    assert stream.seeders == 40
    assert stream.size_display == "5 GB"
    assert stream.size_bytes == int(5 * 1000**3)
    assert stream.indexer == "1337x"
    assert "HEVC/x265" in stream.codecs
    assert "Dolby Vision" not in stream.hdr
    assert "HDR" in stream.hdr
    assert "10-bit" in stream.hdr
    assert "AAC" in stream.audio
    assert "7.1" in stream.audio
    assert stream.is_torrent is True
    assert stream.is_debrid is False


def test_parse_torrentio_debrid_stream():
    sample = {
        "name": "[RD+] Torrentio\n1080p",
        "title": "Movie.1080p.WEB-DL.x264\n💾 2.4 GB ⚙️ RARBG",
        "url": "https://real-debrid.com/d/xyz123/stream.mp4",
    }
    stream = parse_torrentio_stream(sample)
    assert stream.quality == Quality.FHD_1080P
    assert stream.is_debrid is True
    assert stream.source_type == SourceType.DEBRID
    assert stream.url == "https://real-debrid.com/d/xyz123/stream.mp4"
    assert stream.is_http is True


def test_parse_generic_stream():
    sample = {
        "name": "Public Domain Addon",
        "title": "Night of the Living Dead (1968) 1080p Remaster 1.8 GB 25 seeds",
        "url": "https://archive.org/download/night_living_dead/movie.mp4",
    }
    stream = parse_generic_stream(sample, provider_name="Internet Archive")
    assert stream.provider == "Internet Archive"
    assert stream.quality == Quality.FHD_1080P
    assert stream.seeders == 25
    assert stream.size_display == "1.8 GB"
    assert stream.source_type == SourceType.HTTP
    assert stream.url.startswith("https://")
