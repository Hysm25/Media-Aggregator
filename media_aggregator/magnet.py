"""Magnet URI construction, parsing, and BitTorrent client integration."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import urllib.parse
from typing import Dict, List, Optional, Tuple

DEFAULT_TRACKERS: List[str] = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.tracker.cl:1337/announce",
    "udp://9.rarbg.to:2920/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "http://tracker.openbittorrent.com:80/announce",
    "udp://opentracker.i2p.rocks:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://explodie.org:6969/announce",
]


def clean_info_hash(raw_hash: str) -> str:
    """Normalize infoHash to a 40-character lowercase hex string.
    
    Supports both 40-character hexadecimal and 32-character Base32 encoded hashes.
    """
    raw = raw_hash.strip().lower()
    if len(raw) == 40 and all(c in "0123456789abcdef" for c in raw):
        return raw
    
    # Check if Base32 (32 characters, uppercase/lowercase RFC 4648)
    clean_b32 = raw.upper()
    if len(clean_b32) == 32:
        try:
            decoded = base64.b32decode(clean_b32)
            return decoded.hex().lower()
        except Exception:
            pass
            
    return raw


def build_magnet_link(
    info_hash: str,
    display_name: Optional[str] = None,
    trackers: Optional[List[str]] = None,
    file_idx: Optional[int] = None,
) -> str:
    """Build an RFC-compliant Magnet URI from an infoHash and optional metadata."""
    normalized_hash = clean_info_hash(info_hash)
    params: List[Tuple[str, str]] = [("xt", f"urn:btih:{normalized_hash}")]

    if display_name:
        params.append(("dn", display_name.strip()))

    all_trackers = list(dict.fromkeys((trackers or []) + DEFAULT_TRACKERS))
    for tr in all_trackers:
        if tr:
            params.append(("tr", tr))

    if file_idx is not None:
        # BEP-53 standard for selective file downloading
        params.append(("so", str(file_idx)))

    query = urllib.parse.urlencode(params)
    return f"magnet:?{query}"


def parse_magnet_link(magnet_uri: str) -> Dict[str, any]:
    """Parse a Magnet URI and extract info_hash, display name, trackers, and file indices."""
    if not magnet_uri.startswith("magnet:?"):
        raise ValueError("Invalid Magnet URI: Must start with 'magnet:?'")

    parsed = urllib.parse.urlparse(magnet_uri)
    query_params = urllib.parse.parse_qs(parsed.query)

    xt_list = query_params.get("xt", [])
    info_hash = None
    for xt in xt_list:
        if xt.startswith("urn:btih:"):
            info_hash = clean_info_hash(xt[len("urn:btih:"):])
            break

    display_name = query_params.get("dn", [None])[0]
    trackers = query_params.get("tr", [])
    so_param = query_params.get("so", [None])[0]
    file_idx = int(so_param) if so_param and so_param.isdigit() else None

    return {
        "info_hash": info_hash,
        "display_name": display_name,
        "trackers": trackers,
        "file_idx": file_idx,
    }


def save_magnet_file(magnet_uri: str, file_path: str) -> str:
    """Save magnet URI to a file for desktop or torrent client import."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(magnet_uri.strip() + "\n")
    return file_path


def find_system_torrent_client() -> Optional[str]:
    """Detect an installed command-line or system torrent client."""
    candidates = ["aria2c", "transmission-remote", "qbittorrent-nox", "xdg-open"]
    for c in candidates:
        if shutil.which(c):
            return c
    return None


def dispatch_to_torrent_client(magnet_uri: str, client: Optional[str] = None) -> Tuple[bool, str]:
    """Attempt to dispatch a Magnet link to a local torrent client."""
    chosen = client or find_system_torrent_client()
    if not chosen:
        return False, "No supported torrent client found in PATH (aria2c, transmission-remote, qbittorrent-nox, xdg-open)."

    try:
        if chosen == "aria2c":
            cmd = ["aria2c", "--seed-time=0", magnet_uri]
            # Launch in background
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, f"Dispatched download to aria2c (PID launched in background)."
        elif chosen == "xdg-open":
            subprocess.Popen(["xdg-open", magnet_uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, "Dispatched magnet URI to system default handler via xdg-open."
        elif chosen == "transmission-remote":
            res = subprocess.run(["transmission-remote", "-a", magnet_uri], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return True, "Added torrent to transmission-daemon."
            return False, f"transmission-remote failed: {res.stderr.strip()}"
        elif chosen in ("qbittorrent", "qbittorrent-nox"):
            subprocess.Popen([chosen, magnet_uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, f"Dispatched magnet URI to {chosen}."
        else:
            return False, f"Unsupported automatic dispatch client: {chosen}"
    except Exception as e:
        return False, f"Failed to dispatch to {chosen}: {str(e)}"
