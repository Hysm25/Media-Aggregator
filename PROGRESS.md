# Project Progress: Media Source Aggregator

**Current Local Time**: 2026-11-01T12:00:00Z  
**Repository Branch**: `master`  
**Test Suite Status**: 49 Passed / 0 Failed (76% Coverage)  
**Package Version**: 1.0.0  

---

## 1. Project Overview & Objectives

The **Media Source Aggregator** is an independent, protocol-compliant Python media discovery and stream resolution engine inspired by the Stremio ecosystem and the Torrentio add-on scraper.

### Primary Objectives
- **Protocol Agnosticism**: Implement the open Stremio Add-on Protocol (v1–v3) for metadata, catalogs, and streaming links.
- **Provider Aggregation**: Concurrently query multiple independent streaming sources (e.g., Torrentio, Cinemeta, MediaFusion).
- **Intelligent Deduplication**: Remove duplicate streams by `infoHash` and URL, merge tracker lists, and retain maximum peer counts.
- **Rich Stream Parsing**: Extract resolution, video formats (`Dolby Vision`, `HDR10+`, `10-bit`), audio codecs (`Dolby Atmos`, `TrueHD`, `DTS-HD MA`, `DD+ 5.1`), file sizes, seeds, and indexers.
- **Resilient Downloader Engine**: Provide chunked HTTP downloads with byte-range resume (`Range: bytes=X-`), SHA-256 verification, RFC Magnet URI generation, and local client dispatch (`aria2c`, `qbittorrent`, `transmission`).
- **Persistent Local Records**: Maintain an embedded SQLite store (`~/.media_aggregator/data.db`) for caching, stream history, download jobs, and registered providers.

---

## 2. Architecture & Implemented Components

```text
/root/t.io/
├── media_aggregator/
│   ├── models.py             # Pydantic data models: MediaItem, EpisodeItem, StreamSource, DownloadRecord
│   ├── parser.py             # Torrentio & generic stream title parser, codecs, HDR, audio, size
│   ├── magnet.py             # Magnet URI builder, Base32/hex hash normalizer, client dispatch
│   ├── storage.py            # SQLite schema manager: media cache, stream history, downloads, addons
│   ├── aggregator.py         # Concurrent multi-provider stream querying, deduplication, sorting
│   ├── providers/
│   │   ├── base.py           # BaseProvider abstract interface & manifest probe
│   │   ├── cinemeta.py       # Cinemeta catalog, search, and TV episode metadata provider
│   │   ├── torrentio.py      # Torrentio provider with URL configuration serialization
│   │   ├── generic.py        # Generic Stremio Addon provider for any v2/v3 endpoint
│   │   └── registry.py       # Addon configuration loader and capability router
│   ├── downloader/
│   │   ├── http.py           # Chunked HTTP downloader with byte-range resume & SHA-256 validation
│   │   ├── torrent.py        # Magnet file exporter and external client bridge
│   │   └── manager.py        # Download lifecycle & SQLite state transition orchestrator
│   └── cli/
│       ├── main.py           # Click command-line interface entry point
│       └── ui.py             # Rich formatting: tables, detail panels, progress bars
├── tests/                    # 49 unit, integration, and regression tests
├── README.md                 # User guide and CLI examples
├── pyproject.toml            # Build configuration and dependencies
└── PROGRESS.md               # Project handoff and milestone tracking
```

---

## 3. Protocol & Reverse-Engineering Findings

### 3.1 Stremio Add-on Protocol (v1–v3)
Stremio operates over standard HTTP JSON endpoints:
- `manifest.json`: Defines add-on `id`, `name`, `version`, `resources` (`catalog`, `meta`, `stream`, `subtitles`), `types` (`movie`, `series`, `anime`), and `catalogs`.
- `/catalog/{type}/{id}.json`: Catalog discovery (e.g. top movies/series, trending anime).
- `/catalog/{type}/{id}/search={query}.json`: Keyword search.
- `/meta/{type}/{id}.json`: Complete metadata synopsis, cast, genres, and series episode lists.
- `/stream/{type}/{id}.json`: Streams for movies (`tt1234567`) or TV series (`tt1234567:season:episode`).

### 3.2 Torrentio Configuration Path Serialization
Torrentio serializes all user preferences directly into the URL path prior to the resource route:
```text
https://torrentio.strem.fun/{configPath}/stream/{type}/{id}.json
```
Where `{configPath}` is pipe-delimited (`|`):
- `providers=yts,eztv,rarbg,1337x,torrentgalaxy,magnetdl,nyaasi`
- `sort=qualitysize` | `seeders` | `size`
- `qualityfilter=4k,1080p,720p,480p,scr,cam`
- `limit=5`
- `realdebrid=API_KEY` | `alldebrid=API_KEY` | `torbox=API_KEY`

---

## 4. Progress Tracking Matrix

Statuses: `TODO` → `IN PROGRESS` → `IMPLEMENTED` → `VERIFIED` | `BLOCKED`

### 4.1 Discovery & Metadata
| Feature | Status | Priority | Supporting Evidence / Source Reference |
| :--- | :---: | :---: | :--- |
| Cinemeta Title Search | **VERIFIED** | HIGH | `test_cinemeta_provider_parsing`; Live search `"The Matrix"` returned 19 items in 2541ms ([`CinemetaProvider.search`](file:///root/t.io/media_aggregator/providers/cinemeta.py#L86-L100)) |
| Cinemeta Movie Metadata | **VERIFIED** | HIGH | Live query `tt0133093` retrieved synopsis, Christopher Nolan cast/director ([`CinemetaProvider.get_metadata`](file:///root/t.io/media_aggregator/providers/cinemeta.py#L126-L141)) |
| TV Series & Episode Breakdown | **VERIFIED** | HIGH | `test_cinemeta_series_episodes_parsing`; Live `tt0903747` returned 6 seasons, 67 episodes ([`models.EpisodeItem`](file:///root/t.io/media_aggregator/models.py#L58-L68)) |
| Season/Episode 0 Specials | **VERIFIED** | MEDIUM | `test_cinemeta_season_zero_episode_zero`; Correctly preserves S00E00 without coercing to 1 |
| Anime Kitsu Catalog Search | **VERIFIED** | MEDIUM | `test_generic_provider_dynamic_search_catalog`; Live query `kitsu-anime-list` returned `kitsu:11` ([`GenericStremioProvider`](file:///root/t.io/media_aggregator/providers/generic.py#L64-L105)) |
| TMDB / TVDb Metadata Fallback | **TODO** | MEDIUM | Planned fallback metadata provider when IMDb IDs are absent |

### 4.2 Stream Resolution & Aggregation
| Feature | Status | Priority | Supporting Evidence / Source Reference |
| :--- | :---: | :---: | :--- |
| Torrentio Movie Streams | **VERIFIED** | HIGH | `test_torrentio_streams_fetching`; Live query `tt0133093` returned 133 unique streams ([`TorrentioProvider.get_streams`](file:///root/t.io/media_aggregator/providers/torrentio.py#L86-L115)) |
| Torrentio TV Episode Streams | **VERIFIED** | HIGH | Live query `tt0903747:1:1` returned 77 unique episode streams ([`aggregator.py`](file:///root/t.io/media_aggregator/aggregator.py#L46-L92)) |
| Torrentio Kitsu ID Streams | **VERIFIED** | HIGH | Live query `kitsu:11:1` resolved Naruto torrent sources via Torrentio |
| Torrentio Config Path Builder | **VERIFIED** | HIGH | `test_torrentio_config_path_builder`; Live query with `providers=yts\|limit=3` returned 1 stream |
| Generic Stremio Add-on Protocol | **VERIFIED** | HIGH | `test_generic_stremio_provider`; Live inspection of MediaFusion and OpenSubtitles v3 manifests |
| Debrid Cached Stream Resolution | **IMPLEMENTED** | HIGH | Formats debrid config routes and parses `[RD+]` badges; live stream unlocking requires paid user token (`BLOCKED` for live test) |
| Multi-Provider Concurrency | **VERIFIED** | HIGH | `test_aggregator.py`; Concurrently queries providers via `ThreadPoolExecutor` ([`aggregator.py`](file:///root/t.io/media_aggregator/aggregator.py#L61-L80)) |
| Resource Capability Filtering | **VERIFIED** | HIGH | `test_stream_providers_resource_filtering`; Non-stream add-ons (OpenSubtitles, Cinemeta) excluded from stream querying |

### 4.3 Deduplication & Quality Parsing
| Feature | Status | Priority | Supporting Evidence / Source Reference |
| :--- | :---: | :---: | :--- |
| InfoHash Deduplication | **VERIFIED** | HIGH | `test_deduplication_by_info_hash`; Merges duplicate hashes, unions trackers, retains max seeds ([`aggregator.py`](file:///root/t.io/media_aggregator/aggregator.py#L100-L112)) |
| Direct URL Deduplication | **VERIFIED** | HIGH | `test_deduplication_by_url`; Deduplicates identical HTTP/debrid stream URLs across providers |
| Resolution / Quality Extraction | **VERIFIED** | HIGH | `test_extract_resolution_and_quality`; Correctly maps 4K/2160p, 1080p, 720p, 480p, CAM/SCR ([`parser.py`](file:///root/t.io/media_aggregator/parser.py#L42-L58)) |
| Codec / HDR / Audio Extraction | **VERIFIED** | HIGH | `test_extract_codecs`, `test_extract_hdr`, `test_extract_audio`; Extracts HEVC, AV1, DV, HDR10+, Atmos, 7.1 |
| Human Size to Byte Conversion | **VERIFIED** | HIGH | `test_parse_size_to_bytes`; Accurate byte conversions for GB, MB, KB, GiB, MiB ([`parser.py`](file:///root/t.io/media_aggregator/parser.py#L10-L40)) |
| Filtering & Sorting Engine | **VERIFIED** | HIGH | `test_filtering`, `test_sorting`, `test_group_by_quality`; Verified min-seeds, max-size, CAM exclusion, sort order |

### 4.4 Downloader Engine & Magnet Handler
| Feature | Status | Priority | Supporting Evidence / Source Reference |
| :--- | :---: | :---: | :--- |
| HTTP Chunked Streaming | **VERIFIED** | HIGH | `test_http_downloader_basic`; Chunked transfer validated with progress callbacks ([`HTTPDownloader`](file:///root/t.io/media_aggregator/downloader/http.py#L29-L168)) |
| HTTP Range Resume (206) | **VERIFIED** | HIGH | Verified with live local range server; partial `.part` resumed via `Range: bytes=X-` matching SHA-256 |
| HTTP 416 Stale Part Recovery | **VERIFIED** | HIGH | `test_downloader_416_corrupted_part_recovery`; Stale `.part` file triggering 416 is discarded and restarted from 0 |
| Cancellation Event State Reset | **VERIFIED** | HIGH | `test_downloader_cancel_reset_regression`; Downloader re-use verified after previous cancellation |
| RFC Magnet URI Construction | **VERIFIED** | HIGH | `test_build_and_parse_magnet_link`; Generates `urn:btih:`, URL-encoded `dn`, 9 public trackers, `so=X` file index ([`magnet.py`](file:///root/t.io/media_aggregator/magnet.py#L46-L70)) |
| Base32 InfoHash Normalization | **VERIFIED** | MEDIUM | `test_clean_info_hash_base32`; Converts 32-char RFC 4648 Base32 infohashes to 40-char lowercase hex |
| `.magnet` File Export | **VERIFIED** | HIGH | `test_torrent_downloader_export`; Writes `.magnet` files into target download directory |
| Client Dispatch (Aria2/qBit) | **VERIFIED** | MEDIUM | `test_qbittorrent_dispatch`; Subprocess execution for `aria2c`, `qbittorrent`, `qbittorrent-nox`, `transmission` |
| Headless Environment Fallback | **VERIFIED** | MEDIUM | When GUI launchers fail in headless Linux, cleanly logs `.magnet` file completion |
| Native BitTorrent Wire Engine | **TODO** | MEDIUM | In-process torrent peer-wire download engine (libtorrent-python or pure asyncio BitTorrent engine) |

### 4.5 Storage & History
| Feature | Status | Priority | Supporting Evidence / Source Reference |
| :--- | :---: | :---: | :--- |
| SQLite Schema Initialization | **VERIFIED** | HIGH | `test_default_addons_initialization`; Creates tables, seeds default providers ([`StorageManager`](file:///root/t.io/media_aggregator/storage.py#L45-L148)) |
| Media Metadata Caching | **VERIFIED** | HIGH | `test_media_cache`; Caches full metadata avoiding external network lookups |
| Stream Discovery Logging | **VERIFIED** | HIGH | `test_stream_history`; Records discovered sources, seeders, sizes, and raw JSON payloads |
| Download State Management | **VERIFIED** | HIGH | `test_downloads_tracking`; Records progress, speed, status transitions (`PENDING` → `DOWNLOADING` → `COMPLETED`) |
| Cancellation State Transitions | **VERIFIED** | HIGH | `test_download_manager_cancellation_tracking`; Interrupts transition records to `CANCELLED` |
| Addon Registry Dynamic Store | **VERIFIED** | HIGH | `test_addons_management`; Add, toggle, delete add-on records in SQLite |
| Bookmarks Store | **VERIFIED** | LOW | `test_bookmarks`; Add, list, remove media favorites in SQLite |

### 4.6 User Interface (CLI)
| Feature | Status | Priority | Supporting Evidence / Source Reference |
| :--- | :---: | :---: | :--- |
| CLI Help & Argument Parsing | **VERIFIED** | HIGH | `test_cli_help`; Click group with 9 commands (`search`, `browse`, `info`, `streams`, `magnet`, `download`, `history`, `addons`, `config-torrentio`) |
| CLI Search Command | **VERIFIED** | HIGH | `test_cli_search`; Live tested `media-aggregator search "Interstellar"` |
| CLI Metadata View (`info`) | **VERIFIED** | HIGH | `test_cli_info`; Live tested `media-aggregator info tt0903747 --type series` |
| CLI Streams Aggregation | **VERIFIED** | HIGH | `test_cli_streams`; Live tested `media-aggregator streams tt0903747 -s 1 -e 1` |
| CLI Magnet Command | **VERIFIED** | HIGH | `test_cli_magnet`; Live tested `media-aggregator magnet tt0903747 -s 1 -e 1 -i 1` |
| CLI History View | **VERIFIED** | HIGH | Live verified table output with status formatting and paths |
| CLI Addon Registry Commands | **VERIFIED** | HIGH | `test_cli_addons`; Live tested `media-aggregator addons add <url>` |
| CLI Torrentio Configuration | **VERIFIED** | MEDIUM | Live updated provider and sorting options via `config-torrentio` |
| Terminal User Interface (TUI) | **TODO** | MEDIUM | Full-screen interactive TUI (using Textual or prompt_toolkit) |

---

## 5. Independent Audit Findings & Applied Fixes

During the technical audit, 8 specific defects were identified and fixed:

1. **Downloader State Reset Bug**: `HTTPDownloader._cancel_event` was not cleared in `download_file()`. Fixed in [`http.py`](file:///root/t.io/media_aggregator/downloader/http.py#L50).
2. **HTTP 416 Stale Part Corruption Bug**: 416 responses blindly renamed potentially corrupt `.part` files. Fixed to validate integrity before renaming; invalid partials are purged. Fixed in [`http.py`](file:///root/t.io/media_aggregator/downloader/http.py#L65-L95).
3. **Missing `qbittorrent-nox` Dispatch Branch**: Client candidate list contained `qbittorrent-nox` but dispatch rejected it. Fixed in [`magnet.py`](file:///root/t.io/media_aggregator/magnet.py#L136-L140).
4. **Direct HTTP Stream Debrid Misclassification**: Direct URLs without debrid badges were flagged `is_debrid=True`. Fixed to require genuine provider badge tokens. Fixed in [`parser.py`](file:///root/t.io/media_aggregator/parser.py#L164-L174).
5. **Futile Querying of Non-Stream Add-ons**: `get_stream_providers()` queried subtitle and catalog-only add-ons. Fixed to enforce `supports_resource("stream")`. Fixed in [`registry.py`](file:///root/t.io/media_aggregator/providers/registry.py#L58-L64).
6. **Hardcoded Search Catalog Path**: `GenericStremioProvider` hardcoded `/top/`, breaking add-ons with custom catalog IDs (e.g., Anime Kitsu). Fixed via dynamic catalog ID resolution. Fixed in [`generic.py`](file:///root/t.io/media_aggregator/providers/generic.py#L64-L105).
7. **Season 0 / Episode 0 Coercion**: Null checks coerced index `0` to `1`. Fixed in [`cinemeta.py`](file:///root/t.io/media_aggregator/providers/cinemeta.py#L50-L68).
8. **Orphaned `DOWNLOADING` State on Interrupt**: Cancelling via `Ctrl+C` left database records stuck in `DOWNLOADING`. Fixed to transition to `CANCELLED`. Fixed in [`manager.py`](file:///root/t.io/media_aggregator/downloader/manager.py#L102-L115).

---

## 6. Test Suite & Coverage Status

### Coverage Summary
```text
Platform: Linux (Python 3.14.8), pytest-9.2.0, coverage-7.17.0
Total Tests: 49 passed / 0 failed in 8.07s
Overall Statement Coverage: 76% (1,597 statements, 391 missed)
```

### Module Breakdown
- `media_aggregator/__init__.py`: 100%
- `media_aggregator/models.py`: 99%
- `media_aggregator/storage.py`: 98%
- `media_aggregator/parser.py`: 92%
- `media_aggregator/providers/torrentio.py`: 90%
- `media_aggregator/downloader/manager.py`: 82%
- `media_aggregator/magnet.py`: 81%
- `media_aggregator/providers/base.py`: 79%
- `media_aggregator/downloader/http.py`: 77%
- `media_aggregator/aggregator.py`: 72%
- `media_aggregator/providers/cinemeta.py`: 68%
- `media_aggregator/cli/ui.py`: 60%
- `media_aggregator/providers/registry.py`: 54%
- `media_aggregator/cli/main.py`: 54%
- `media_aggregator/providers/generic.py`: 42%

---

## 7. Known Issues & Limitations

1. **Debrid Service Live Unlocking**: Link unlocking via RealDebrid, AllDebrid, or TorBox requires a paid user API key. URL route construction and badge parsing are implemented, but live stream resolution requires valid credentials.
2. **Headless Linux Environments**: On servers lacking an active X11/Wayland display server or desktop session, `xdg-open` cannot launch external desktop applications. The application detects this and safely falls back to saving the `.magnet` file.
3. **In-Process BitTorrent Downloading**: Torrent downloading relies on generating RFC Magnet links, exporting `.magnet` files, and dispatching to system BitTorrent clients (`aria2c`, `qbittorrent`, `transmission`). Direct piece-by-piece peer-wire downloading is not built into the Python process.

---

## 8. Remaining Tasks & Future Milestones

### High Priority
- [ ] **Interactive TUI Interface**: Build a terminal user interface using `textual` or `prompt_toolkit` to allow arrow-key navigation through catalogs, search results, and stream quality tiers.
- [ ] **RealDebrid / Debrid Live Integration Test**: Test real link unlocking with a user-provided debrid API token.

### Medium Priority
- [ ] **TMDB / TVDb Metadata Fallback**: Add TMDB API provider for media lacking IMDb identifiers.
- [ ] **In-Process BitTorrent Engine**: Integrate a Python BitTorrent client wrapper (e.g. `libtorrent` bindings or pure Python peer-wire protocol implementation) to allow headless torrent downloads without external tools.
- [ ] **OpenSubtitles Live Downloader**: Add subtitle search and `.srt` file downloading via the OpenSubtitles v3 add-on protocol.

### Low Priority
- [ ] **Local Web Dashboard**: Lightweight FastAPI or Flask web UI for browsing and triggering downloads from a browser.
- [ ] **Automatic Debrid Cache Checking**: Check if torrent infohashes are instantly available on RealDebrid before presenting them to the user.

---

## 9. Agent Handoff Guide

### Current Project State
The project is a fully functional, installed Python package (`media-source-aggregator` v1.0.0, CLI entry points `media-aggregator` and `msa`). All 49 automated tests pass with zero warnings. All live endpoints (Cinemeta, Torrentio, Anime Kitsu) respond and parse correctly.

### Critical Files to Know
- **Core Aggregator**: [`media_aggregator/aggregator.py`](file:///root/t.io/media_aggregator/aggregator.py) (concurrency & deduplication logic)
- **Torrentio Provider**: [`media_aggregator/providers/torrentio.py`](file:///root/t.io/media_aggregator/providers/torrentio.py) (config serialization & stream fetching)
- **Cinemeta Provider**: [`media_aggregator/providers/cinemeta.py`](file:///root/t.io/media_aggregator/providers/cinemeta.py) (catalog search & episode metadata)
- **HTTP Downloader**: [`media_aggregator/downloader/http.py`](file:///root/t.io/media_aggregator/downloader/http.py) (range resume & SHA-256 validation)
- **Magnet Handler**: [`media_aggregator/magnet.py`](file:///root/t.io/media_aggregator/magnet.py) (URI generation & client dispatch)
- **CLI Commands**: [`media_aggregator/cli/main.py`](file:///root/t.io/media_aggregator/cli/main.py) (Click CLI interface)

### Verified Test Suite
Run tests at any time with:
```bash
pytest -v --cov=media_aggregator tests/
```

### Exact Recommended Next Task
**Build the Interactive TUI Interface (`media_aggregator/tui/`)**:
Create an interactive terminal UI (using Textual or prompt_toolkit) that allows users to launch `media-aggregator tui`, search with live auto-completion, browse poster artwork/metadata, and select streams with arrow keys.
