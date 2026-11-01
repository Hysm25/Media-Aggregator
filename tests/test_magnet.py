"""Tests for Magnet link handling and BitTorrent client integration."""

import os
import tempfile
import pytest
from media_aggregator.magnet import (
    build_magnet_link,
    clean_info_hash,
    parse_magnet_link,
    save_magnet_file,
)


def test_clean_info_hash_hex():
    hex_hash = "3C86B78EFA012A402C28712D8BE282D813F1A279"
    assert clean_info_hash(hex_hash) == hex_hash.lower()


def test_clean_info_hash_base32():
    # Base32 representation of a 20-byte hash
    # SHA-1: da39a3ee5e6b4b0d3255bfef95601890afd80709
    b32 = "3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ"
    normalized = clean_info_hash(b32)
    assert len(normalized) == 40
    assert normalized == "da39a3ee5e6b4b0d3255bfef95601890afd80709"


def test_build_and_parse_magnet_link():
    info_hash = "502d3432f7967048495ad18c9f8ccd821f04ef3c"
    title = "Big.Hero.6.2014.2160p.UHD.BluRay"
    trackers = ["udp://tracker.opentrackr.org:1337/announce"]
    file_idx = 2

    magnet = build_magnet_link(
        info_hash=info_hash,
        display_name=title,
        trackers=trackers,
        file_idx=file_idx,
    )

    assert magnet.startswith("magnet:?")
    assert f"xt=urn%3Abtih%3A{info_hash}" in magnet
    assert "dn=Big.Hero.6.2014.2160p.UHD.BluRay" in magnet
    assert "so=2" in magnet

    parsed = parse_magnet_link(magnet)
    assert parsed["info_hash"] == info_hash
    assert parsed["display_name"] == title
    assert parsed["file_idx"] == 2
    assert "udp://tracker.opentrackr.org:1337/announce" in parsed["trackers"]


def test_save_magnet_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "test.magnet")
        magnet_uri = "magnet:?xt=urn:btih:3c86b78efa012a402c28712d8be282d813f1a279&dn=Test"
        saved = save_magnet_file(magnet_uri, file_path)
        assert os.path.exists(saved)
        with open(saved, "r") as f:
            content = f.read().strip()
        assert content == magnet_uri
