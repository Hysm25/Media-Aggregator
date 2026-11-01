"""Stream title, metadata, and quality parsing for Stremio and Torrentio streams."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from media_aggregator.models import Quality, SourceType, StreamSource


def parse_size_to_bytes(size_str: Optional[str]) -> Optional[int]:
    """Convert human-readable size strings (e.g. '10.31 GB', '750 MB') to bytes."""
    if not size_str:
        return None

    cleaned = size_str.strip().replace(",", ".")
    match = re.search(r"([\d\.]+)\s*([KMGTPE]?i?B)", cleaned, re.IGNORECASE)
    if not match:
        return None

    val_str, unit_str = match.groups()
    try:
        val = float(val_str)
    except ValueError:
        return None

    unit = unit_str.upper()
    multipliers = {
        "B": 1,
        "KB": 1000,
        "KIB": 1024,
        "MB": 1000**2,
        "MIB": 1024**2,
        "GB": 1000**3,
        "GIB": 1024**3,
        "TB": 1000**4,
        "TIB": 1024**4,
    }
    multiplier = multipliers.get(unit, 1024**2)
    return int(val * multiplier)


def extract_resolution_and_quality(text: str) -> Tuple[str, Quality]:
    """Extract standard resolution string and Quality enum from title/name."""
    t = text.lower()

    if re.search(r"\b(hdcam|cam|camrip|ts|hdts|telesync|scr|screener|dvdscr)\b", t):
        return "CAM/SCR", Quality.CAM_SCR
    if re.search(r"\b(2160p|4k|uhd)\b", t):
        return "4K (2160p)", Quality.UHD_4K
    if re.search(r"\b(1080p|1080i|fhd)\b", t):
        return "1080p", Quality.FHD_1080P
    if re.search(r"\b(720p|hd)\b", t):
        return "720p", Quality.HD_720P
    if re.search(r"\b(480p|576p|sd|dvdrip)\b", t):
        return "480p", Quality.SD_480P

    return "Unknown", Quality.UNKNOWN


def extract_codecs(text: str) -> List[str]:
    """Extract video codecs from text."""
    codecs = []
    t = text.upper()
    if "AV1" in t:
        codecs.append("AV1")
    if "HEVC" in t or "H.265" in t or "H265" in t or "X265" in t:
        codecs.append("HEVC/x265")
    elif "H.264" in t or "H264" in t or "X264" in t or "AVC" in t:
        codecs.append("AVC/x264")
    if "XVID" in t or "DIVX" in t:
        codecs.append("XviD")
    return codecs


def extract_hdr(text: str) -> List[str]:
    """Extract HDR / color formats from text."""
    hdr = []
    t = text.upper()
    if "DV" in t or "DOVI" in t or "DOLBY VISION" in t:
        hdr.append("Dolby Vision")
    if "HDR10+" in t or "HDR10PLUS" in t:
        hdr.append("HDR10+")
    elif "HDR10" in t:
        hdr.append("HDR10")
    elif "HDR" in t:
        hdr.append("HDR")
    if "10BIT" in t or "10-BIT" in t:
        hdr.append("10-bit")
    return hdr


def extract_audio(text: str) -> List[str]:
    """Extract audio codecs and channel configurations from text."""
    audio = []
    t = text.upper()
    if "ATMOS" in t:
        audio.append("Dolby Atmos")
    if "TRUEHD" in t:
        audio.append("TrueHD")
    if "DTS-HD" in t or "DTSHD" in t or "DTS-HD MA" in t:
        audio.append("DTS-HD MA")
    elif "DTS" in t:
        audio.append("DTS")
    if "EAC3" in t or "DDP" in t or "DD+" in t:
        audio.append("DD+")
    elif "AC3" in t or "DD5.1" in t:
        audio.append("AC3")
    if "AAC" in t:
        audio.append("AAC")
    if "FLAC" in t:
        audio.append("FLAC")

    if re.search(r"\b7[\. ]1\b", t):
        audio.append("7.1")
    elif re.search(r"\b5[\. ]1\b", t):
        audio.append("5.1")
    elif re.search(r"\b2[\. ]0\b", t):
        audio.append("2.0")

    return list(dict.fromkeys(audio))


def parse_torrentio_stream(raw: Dict[str, Any], provider_name: str = "Torrentio") -> StreamSource:
    """Parse a stream dictionary from Torrentio into a normalized StreamSource object."""
    name = raw.get("name", "")
    title = raw.get("title", "")
    info_hash = raw.get("infoHash")
    file_idx = raw.get("fileIdx")
    url = raw.get("url")
    behavior_hints = raw.get("behaviorHints", {})

    lines = [line.strip() for line in title.split("\n") if line.strip()]
    release_title = lines[0] if lines else name
    inner_filename = None

    seeders: Optional[int] = None
    size_str: Optional[str] = None
    indexer: Optional[str] = None
    languages: List[str] = []

    # Check for metadata line (typically contains emojis 👤, 💾, ⚙️)
    for line in lines[1:]:
        if "👤" in line or "💾" in line or "⚙️" in line:
            # Seeders: 👤 40
            seed_match = re.search(r"👤\s*(\d+)", line)
            if seed_match:
                seeders = int(seed_match.group(1))

            # Size: 💾 10.31 GB
            size_match = re.search(r"💾\s*([\d\.]+\s*(?:GB|MB|KB|B))", line, re.IGNORECASE)
            if size_match:
                size_str = size_match.group(1)

            # Indexer: ⚙️ RARBG / 1337x
            indexer_match = re.search(r"⚙️\s*([^\n\r]+)", line)
            if indexer_match:
                indexer = indexer_match.group(1).strip()
        elif any(flag in line for flag in ["🇬🇧", "🇺🇸", "🇫🇷", "🇩🇪", "🇮🇹", "🇪🇸", "🇯🇵", "🇷🇺"]) or "Multi Audio" in line:
            languages.append(line)
        elif not inner_filename and any(line.endswith(ext) for ext in [".mkv", ".mp4", ".avi", ".ts"]):
            inner_filename = line

    # Determine source type
    # Debrid providers embed tag badges in the stream name/title (e.g., [RD+], [AD+], [PM+], [TB+], [DL+])
    has_debrid_badge = bool(
        re.search(r"\[(RD|AD|PM|TB|DL|OC|PO)\+?\]", f"{name} {title}", re.IGNORECASE)
    )
    is_debrid = has_debrid_badge
    if is_debrid:
        source_type = SourceType.DEBRID
    elif info_hash:
        source_type = SourceType.TORRENT
    elif url:
        source_type = SourceType.HTTP
    else:
        source_type = SourceType.UNKNOWN

    combined_text = f"{name} {title} {inner_filename or ''}"
    resolution, quality = extract_resolution_and_quality(combined_text)
    codecs = extract_codecs(combined_text)
    hdr = extract_hdr(combined_text)
    audio = extract_audio(combined_text)
    size_bytes = parse_size_to_bytes(size_str)

    trackers = []
    for s in raw.get("sources", []):
        if isinstance(s, str) and s.startswith("tracker:"):
            trackers.append(s[len("tracker:"):])

    stream_id = info_hash or url or f"{release_title}_{file_idx}"

    return StreamSource(
        id=str(stream_id),
        provider=provider_name,
        name=name,
        title=title,
        release_title=release_title,
        inner_filename=inner_filename,
        info_hash=info_hash,
        file_idx=file_idx,
        url=url,
        quality=quality,
        resolution=resolution,
        source_type=source_type,
        seeders=seeders,
        size_bytes=size_bytes,
        size_display=size_str,
        indexer=indexer,
        codecs=codecs,
        audio=audio,
        hdr=hdr,
        languages=languages,
        behavior_hints=behavior_hints,
        trackers=trackers,
        is_debrid=is_debrid,
    )


def parse_generic_stream(raw: Dict[str, Any], provider_name: str) -> StreamSource:
    """Parse a stream dictionary from any standard Stremio add-on."""
    name = raw.get("name") or provider_name
    title = raw.get("title") or raw.get("description") or name
    info_hash = raw.get("infoHash")
    file_idx = raw.get("fileIdx")
    url = raw.get("url") or raw.get("externalUrl")
    behavior_hints = raw.get("behaviorHints", {})

    # Check for direct magnet link in url or externalUrl
    if not info_hash and url and url.startswith("magnet:?"):
        from media_aggregator.magnet import parse_magnet_link
        parsed_magnet = parse_magnet_link(url)
        if parsed_magnet and parsed_magnet.get("info_hash"):
            info_hash = parsed_magnet["info_hash"]
            if file_idx is None and parsed_magnet.get("file_idx") is not None:
                file_idx = parsed_magnet["file_idx"]

    # Check for YouTube ytId
    if not url and raw.get("ytId"):
        url = f"https://www.youtube.com/watch?v={raw['ytId']}"

    combined_text = f"{name} {title}"
    resolution, quality = extract_resolution_and_quality(combined_text)
    codecs = extract_codecs(combined_text)
    hdr = extract_hdr(combined_text)
    audio = extract_audio(combined_text)

    # Check for seeders or size in title if present
    seeders = None
    seed_match = re.search(r"(?:👤\s*(\d+)|\b(\d+)\s*(?:seeds|seeders|peer)\b)", combined_text, re.IGNORECASE)
    if seed_match:
        seeders = int(seed_match.group(1) or seed_match.group(2))

    size_bytes = None
    size_str = None
    size_match = re.search(r"\b([\d\.]+\s*(?:GB|MB|KB|GiB|MiB))\b", combined_text, re.IGNORECASE)
    if size_match:
        size_str = size_match.group(1)
        size_bytes = parse_size_to_bytes(size_str)

    if info_hash or (url and url.startswith("magnet:?")):
        source_type = SourceType.TORRENT
    elif url and (url.startswith("http://") or url.startswith("https://")):
        source_type = SourceType.HTTP
    else:
        source_type = SourceType.UNKNOWN

    trackers = []
    for s in raw.get("sources", []):
        if isinstance(s, str) and s.startswith("tracker:"):
            trackers.append(s[len("tracker:"):])

    stream_id = info_hash or url or f"{title}_{file_idx}"

    return StreamSource(
        id=str(stream_id),
        provider=provider_name,
        name=name,
        title=title,
        release_title=title.split("\n")[0],
        info_hash=info_hash,
        file_idx=file_idx,
        url=url,
        quality=quality,
        resolution=resolution,
        source_type=source_type,
        seeders=seeders,
        size_bytes=size_bytes,
        size_display=size_str,
        codecs=codecs,
        audio=audio,
        hdr=hdr,
        behavior_hints=behavior_hints,
        trackers=trackers,
    )
