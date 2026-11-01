"""Rich terminal presentation components for Media Source Aggregator."""

from __future__ import annotations

from typing import Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from media_aggregator.models import (
    AddonConfig,
    DownloadRecord,
    EpisodeItem,
    MediaItem,
    MediaType,
    StreamSource,
)

console = Console()


def format_bytes(size_bytes: Optional[int]) -> str:
    """Format bytes into readable size."""
    if not size_bytes:
        return "N/A"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:3.1f} {unit}"
        size_bytes /= 1024.0  # type: ignore
    return f"{size_bytes:.1f} PB"


def display_media_list(items: List[MediaItem], title: str = "Search Results") -> None:
    """Render a table of media search or catalog results."""
    table = Table(title=title, show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("IMDb ID", style="bold yellow", width=12)
    table.add_column("Title", style="bold white")
    table.add_column("Type", style="magenta", width=8)
    table.add_column("Year", style="green", width=6)
    table.add_column("Rating", style="bold bright_yellow", width=8)
    table.add_column("Genres", style="cyan")

    for item in items:
        genres_str = ", ".join(item.genres[:3]) if item.genres else "-"
        rating_str = f"⭐ {item.imdb_rating}" if item.imdb_rating else "-"
        table.add_row(
            item.id,
            item.title,
            item.type.value.capitalize(),
            item.display_year,
            rating_str,
            genres_str,
        )

    console.print(table)


def display_media_details(item: MediaItem) -> None:
    """Render a detailed panel of a single media item and its episodes."""
    content = Text()
    content.append(f"Title: ", style="bold cyan")
    content.append(f"{item.title}\n", style="bold white")
    content.append(f"Type: ", style="bold cyan")
    content.append(f"{item.type.value.capitalize()}   |   ", style="white")
    content.append(f"Year: ", style="bold cyan")
    content.append(f"{item.display_year}   |   ", style="white")
    content.append(f"Rating: ", style="bold cyan")
    content.append(f"⭐ {item.imdb_rating or 'N/A'}\n", style="bold bright_yellow")

    if item.genres:
        content.append(f"Genres: ", style="bold cyan")
        content.append(f"{', '.join(item.genres)}\n", style="white")

    if item.director:
        content.append(f"Director: ", style="bold cyan")
        content.append(f"{item.director}\n", style="white")

    if item.cast:
        content.append(f"Cast: ", style="bold cyan")
        content.append(f"{', '.join(item.cast[:6])}\n", style="white")

    if item.runtime:
        content.append(f"Runtime: ", style="bold cyan")
        content.append(f"{item.runtime}\n", style="white")

    if item.synopsis:
        content.append(f"\nSynopsis:\n", style="bold yellow")
        content.append(f"{item.synopsis}\n", style="italic")

    panel = Panel(
        content,
        title=f"🎬 [bold green]{item.title}[/bold green] ({item.display_year})",
        border_style="cyan",
    )
    console.print(panel)

    # If TV Series, display episodes summary
    if item.episodes:
        seasons: Dict[int, List[EpisodeItem]] = {}
        for ep in item.episodes:
            seasons.setdefault(ep.season, []).append(ep)

        ep_table = Table(
            title=f"📺 Seasons & Episodes ({len(seasons)} seasons, {len(item.episodes)} episodes)",
            header_style="bold magenta",
            border_style="dim",
        )
        ep_table.add_column("Season", style="cyan", width=8)
        ep_table.add_column("Episode", style="green", width=8)
        ep_table.add_column("ID", style="bold yellow", width=18)
        ep_table.add_column("Title", style="white")
        ep_table.add_column("Air Date", style="dim", width=12)

        for s_num in sorted(seasons.keys()):
            for ep in seasons[s_num][:15]:  # Show first 15 per season for clarity
                air_date = ep.released[:10] if ep.released else "-"
                ep_table.add_row(f"S{ep.season:02d}", f"E{ep.episode:02d}", ep.id, ep.title, air_date)
            if len(seasons[s_num]) > 15:
                ep_table.add_row(
                    f"S{s_num:02d}",
                    "...",
                    "...",
                    f"... ({len(seasons[s_num]) - 15} more episodes in season {s_num})",
                    "",
                )

        console.print(ep_table)


def display_stream_sources(streams: List[StreamSource], media_title: str) -> None:
    """Render aggregated and deduplicated streaming sources."""
    if not streams:
        console.print("[yellow]No stream sources found for this media item.[/yellow]")
        return

    table = Table(
        title=f"⚡ Available Streaming Sources for: [bold green]{media_title}[/bold green] ({len(streams)} unique)",
        show_header=True,
        header_style="bold white on blue",
        border_style="bright_blue",
    )
    table.add_column("#", style="bold cyan", width=4)
    table.add_column("Quality", style="bold yellow", width=14)
    table.add_column("Type", style="magenta", width=9)
    table.add_column("Size", style="green", width=10)
    table.add_column("Seeds", style="bold bright_cyan", width=7)
    table.add_column("HDR / Audio", style="dim cyan", width=18)
    table.add_column("Provider / Indexer", style="dim", width=20)
    table.add_column("Release Title", style="white", no_wrap=False)

    for idx, s in enumerate(streams, start=1):
        # Format tags
        hdr_audio = []
        if s.hdr:
            hdr_audio.extend(s.hdr)
        if s.audio:
            hdr_audio.extend(s.audio[:2])
        hdr_audio_str = " | ".join(hdr_audio) if hdr_audio else "-"

        type_badge = "⚡ Debrid" if s.is_debrid else ("🧲 Torrent" if s.is_torrent else "🌐 HTTP")
        seeds_str = str(s.seeders) if s.seeders is not None else "-"
        size_str = s.size_display or (format_bytes(s.size_bytes) if s.size_bytes else "-")

        indexer_provider = f"{s.provider}"
        if s.indexer:
            indexer_provider += f" ({s.indexer})"

        table.add_row(
            str(idx),
            s.resolution,
            type_badge,
            size_str,
            seeds_str,
            hdr_audio_str,
            indexer_provider,
            s.release_title or s.title.split("\n")[0],
        )

    console.print(table)


def display_download_history(records: List[DownloadRecord]) -> None:
    """Display past and current download history."""
    if not records:
        console.print("[yellow]No download history records found.[/yellow]")
        return

    table = Table(
        title="📥 Download History & Local Records",
        header_style="bold white on magenta",
        border_style="magenta",
    )
    table.add_column("ID", style="bold yellow", width=5)
    table.add_column("Title", style="white")
    table.add_column("Type", style="cyan", width=9)
    table.add_column("Status", style="bold", width=12)
    table.add_column("Progress", style="green", width=10)
    table.add_column("Path / Message", style="dim")
    table.add_column("Date", style="dim", width=16)

    status_styles = {
        "completed": "[bold green]COMPLETED[/bold green]",
        "downloading": "[bold cyan]DOWNLOADING[/bold cyan]",
        "pending": "[yellow]PENDING[/yellow]",
        "failed": "[bold red]FAILED[/bold red]",
        "cancelled": "[dim red]CANCELLED[/dim red]",
    }

    for r in records:
        status_display = status_styles.get(r.status.value, r.status.value)
        progress_str = f"{r.progress_percent:3.1f}%" if r.total_bytes > 0 else "-"
        date_str = r.created_at.strftime("%Y-%m-%d %H:%M")
        msg = r.local_path or r.error_message or "-"

        table.add_row(
            str(r.id),
            r.media_title,
            r.source_type.value.capitalize(),
            status_display,
            progress_str,
            msg,
            date_str,
        )

    console.print(table)


def display_addons_table(addons: List[AddonConfig]) -> None:
    """Display registered add-on providers."""
    table = Table(title="🔌 Registered Stremio Add-on Providers", header_style="bold cyan", border_style="cyan")
    table.add_column("ID", style="bold yellow")
    table.add_column("Name", style="white")
    table.add_column("Base URL", style="dim")
    table.add_column("Priority", style="magenta", width=8)
    table.add_column("Status", style="bold", width=10)

    for a in addons:
        status = "[green]ENABLED[/green]" if a.enabled else "[dim red]DISABLED[/dim red]"
        table.add_row(a.id, a.name, a.base_url, str(a.priority), status)

    console.print(table)
