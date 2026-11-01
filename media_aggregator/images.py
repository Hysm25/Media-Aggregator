"""Cinemeta and external image optimization, quality enhancement, and validation utilities."""

from __future__ import annotations

import re
import urllib.parse
from typing import Optional


def is_valid_image_url(url: Optional[str]) -> bool:
    """Check if a URL is a valid external HTTP/HTTPS image URL."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        return False
    # Avoid local or broken URLs
    try:
        parsed = urllib.parse.urlparse(u)
        host = (parsed.hostname or "").lower()
        if not host or host in ("localhost", "127.0.0.1", "0.0.0.0"):
            return False
        return True
    except Exception:
        return False


def enhance_poster_url(url: Optional[str], imdb_id: Optional[str] = None) -> Optional[str]:
    """Enhance portrait poster URL to maximum resolution and quality.
    
    1. Upgrades Metahub '/poster/small/' thumbnails to crisp '/poster/medium/'.
    2. Strips thumbnail downscaling and cropping params from IMDb/Amazon CDN
       (e.g., '._V1_SX250.jpg' -> '._V1_SX800.jpg').
    3. Falls back to official Cinemeta Metahub portrait poster for confirmed IMDb IDs ('tt...').
    """
    clean_id = imdb_id.strip() if imdb_id and isinstance(imdb_id, str) else None

    if not url or not is_valid_image_url(url):
        if clean_id and clean_id.startswith("tt"):
            return f"https://images.metahub.space/poster/medium/{clean_id}/img"
        return None

    u = url.strip()

    # Metahub small poster upgrade
    if "images.metahub.space/poster/small/" in u:
        return u.replace("/poster/small/", "/poster/medium/")

    # Amazon / IMDb CDN downscaling removal
    if ("media-amazon.com/images/" in u or "ia.media-imdb.com/images/" in u) and "._V1_" in u:
        # e.g., '..._V1_SX250.jpg', '..._V1_UX182_CR0,0,182,268_AL_.jpg'
        return re.sub(r"\._V1_.*?\.(jpg|jpeg|png)$", r"._V1_SX800.\1", u, flags=re.IGNORECASE)

    return u


def enhance_background_url(url: Optional[str], imdb_id: Optional[str] = None) -> Optional[str]:
    """Enhance landscape background artwork URL.
    
    1. Upgrades Metahub '/background/small/' to '/background/medium/'.
    2. Falls back to official Metahub landscape background for confirmed IMDb IDs ('tt...').
    """
    clean_id = imdb_id.strip() if imdb_id and isinstance(imdb_id, str) else None

    if not url or not is_valid_image_url(url):
        if clean_id and clean_id.startswith("tt"):
            return f"https://images.metahub.space/background/medium/{clean_id}/img"
        return None

    u = url.strip()
    if "images.metahub.space/background/small/" in u:
        return u.replace("/background/small/", "/background/medium/")

    if ("media-amazon.com/images/" in u or "ia.media-imdb.com/images/" in u) and "._V1_" in u:
        return re.sub(r"\._V1_.*?\.(jpg|jpeg|png)$", r"._V1_SX1280.\1", u, flags=re.IGNORECASE)

    return u


def enhance_logo_url(url: Optional[str], imdb_id: Optional[str] = None) -> Optional[str]:
    """Enhance official media logo URL.
    
    1. Upgrades Metahub '/logo/small/' to '/logo/medium/'.
    2. Falls back to official Metahub transparent logo for confirmed IMDb IDs ('tt...').
    """
    clean_id = imdb_id.strip() if imdb_id and isinstance(imdb_id, str) else None

    if not url or not is_valid_image_url(url):
        if clean_id and clean_id.startswith("tt"):
            return f"https://images.metahub.space/logo/medium/{clean_id}/img"
        return None

    u = url.strip()
    if "images.metahub.space/logo/small/" in u:
        return u.replace("/logo/small/", "/logo/medium/")

    return u
