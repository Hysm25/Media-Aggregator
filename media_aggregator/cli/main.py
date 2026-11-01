"""Command Line Interface for Media Source Aggregator."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional
import click
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TimeRemainingColumn, TransferSpeedColumn
from media_aggregator.aggregator import StreamAggregator
from media_aggregator.cli.ui import (
    console,
    display_addons_table,
    display_download_history,
    display_media_details,
    display_media_list,
    display_stream_sources,
)
from media_aggregator.downloader.manager import DownloadManager
from media_aggregator.models import MediaType, Quality, SourceType
from media_aggregator.providers.registry import ProviderRegistry
from media_aggregator.storage import StorageManager


@click.group()
def cli() -> None:
    """🎬 Media Source Aggregator: Independent Stremio & Torrentio Stream Engine."""
    pass


@cli.command("search")
@click.argument("query")
@click.option(
    "--type",
    "-t",
    "media_type",
    type=click.Choice(["movie", "series", "anime"], case_sensitive=False),
    default="movie",
    help="Media category to search.",
)
def search_cmd(query: str, media_type: str) -> None:
    """🔍 Search movies or TV shows by title or keywords."""
    registry = ProviderRegistry()
    m_type = MediaType(media_type.lower())
    discovery = registry.get_discovery_provider(media_type=m_type)

    with console.status(f"[bold cyan]Searching {m_type.value}s for '{query}'...[/bold cyan]"):
        results = discovery.search(query=query, media_type=m_type)

    if not results:
        console.print(f"[yellow]No results found for '{query}'.[/yellow]")
        return

    display_media_list(results, title=f"Search Results for '{query}' ({len(results)} found)")


@cli.command("browse")
@click.option(
    "--type",
    "-t",
    "media_type",
    type=click.Choice(["movie", "series"], case_sensitive=False),
    default="movie",
    help="Category to browse.",
)
@click.option("--catalog", "-c", default="top", help="Catalog identifier (e.g. top, year).")
@click.option("--genre", "-g", default=None, help="Optional genre filter (e.g. Action, Comedy).")
def browse_cmd(media_type: str, catalog: str, genre: Optional[str]) -> None:
    """🌐 Browse top or popular catalogs."""
    registry = ProviderRegistry()
    discovery = registry.get_discovery_provider()
    m_type = MediaType(media_type.lower())
    extra = {"genre": genre} if genre else None

    with console.status(f"[bold cyan]Browsing {catalog} {m_type.value}s...[/bold cyan]"):
        results = discovery.get_catalog(media_type=m_type, catalog_id=catalog, extra=extra)

    if not results:
        console.print("[yellow]Catalog returned no entries.[/yellow]")
        return

    title = f"Top {m_type.value.capitalize()}s" + (f" ({genre})" if genre else "")
    display_media_list(results, title=title)


@cli.command("info")
@click.argument("media_id")
@click.option(
    "--type",
    "-t",
    "media_type",
    type=click.Choice(["movie", "series", "anime"], case_sensitive=False),
    default="movie",
    help="Media category.",
)
def info_cmd(media_id: str, media_type: str) -> None:
    """📖 Fetch detailed metadata, synopsis, cast, and episode list."""
    registry = ProviderRegistry()
    discovery = registry.get_discovery_provider()
    storage = StorageManager()
    m_type = MediaType(media_type.lower())

    # Check cache first
    cached = storage.get_media_item(media_id)
    if cached and cached.synopsis:
        display_media_details(cached)
        return

    with console.status(f"[bold cyan]Retrieving metadata for {media_id}...[/bold cyan]"):
        item = discovery.get_metadata(media_type=m_type, media_id=media_id)

    if not item:
        console.print(f"[bold red]Could not find metadata for ID: {media_id}[/bold red]")
        return

    # Cache locally
    storage.save_media_item(item)
    display_media_details(item)


@cli.command("streams")
@click.argument("media_id")
@click.option("--season", "-s", type=int, default=None, help="TV season number (for series).")
@click.option("--episode", "-e", type=int, default=None, help="TV episode number (for series).")
@click.option(
    "--type",
    "-t",
    "media_type",
    type=click.Choice(["movie", "series", "anime"], case_sensitive=False),
    default="movie",
    help="Media category.",
)
@click.option(
    "--sort",
    type=click.Choice(["quality", "seeders", "size_desc", "size_asc", "source_type"], case_sensitive=False),
    default="quality",
    help="Ranking & sorting strategy.",
)
@click.option("--min-seeds", type=int, default=None, help="Minimum peer count filter.")
@click.option("--max-size-gb", type=float, default=None, help="Maximum file size in GB.")
@click.option("--allow-cam", is_flag=True, default=False, help="Include CAM/Screener releases.")
@click.option(
    "--quality",
    type=click.Choice(["4K", "1080p", "720p", "480p"], case_sensitive=False),
    default=None,
    help="Filter to specific resolution.",
)
@click.option("--json-out", is_flag=True, default=False, help="Output streams as JSON.")
def streams_cmd(
    media_id: str,
    season: Optional[int],
    episode: Optional[int],
    media_type: str,
    sort: str,
    min_seeds: Optional[int],
    max_size_gb: Optional[float],
    allow_cam: bool,
    quality: Optional[str],
    json_out: bool,
) -> None:
    """⚡ Aggregate, deduplicate, and display streaming sources."""
    m_type = MediaType(media_type.lower())
    aggregator = StreamAggregator()

    with console.status(f"[bold cyan]Aggregating sources for {media_id}...[/bold cyan]"):
        streams = aggregator.aggregate_streams(
            media_type=m_type,
            media_id=media_id,
            season=season,
            episode=episode,
        )

    # Filtering
    max_bytes = int(max_size_gb * (1024**3)) if max_size_gb else None
    qualities = [Quality(quality)] if quality else None

    filtered = aggregator.filter_streams(
        streams,
        min_seeders=min_seeds,
        max_size_bytes=max_bytes,
        exclude_cam=not allow_cam,
        allowed_qualities=qualities,
    )

    # Sorting
    sorted_streams = aggregator.sort_streams(filtered, sort_by=sort)

    if json_out:
        output_data = [s.model_dump() for s in sorted_streams]
        click.echo(json.dumps(output_data, indent=2, default=str))
        return

    # Lookup media title if available
    storage = StorageManager()
    media_item = storage.get_media_item(media_id)
    title = media_item.title if media_item else media_id
    if season and episode:
        title = f"{title} (S{season:02d}E{episode:02d})"

    display_stream_sources(sorted_streams, media_title=title)


@cli.command("magnet")
@click.argument("media_id")
@click.option("--season", "-s", type=int, default=None, help="TV season number.")
@click.option("--episode", "-e", type=int, default=None, help="TV episode number.")
@click.option(
    "--type",
    "-t",
    "media_type",
    type=click.Choice(["movie", "series", "anime"], case_sensitive=False),
    default="movie",
    help="Media category.",
)
@click.option("--index", "-i", type=int, default=1, help="1-based stream index from streams table.")
def magnet_cmd(media_id: str, season: Optional[int], episode: Optional[int], media_type: str, index: int) -> None:
    """🧲 Generate and display Magnet URI for an aggregated stream."""
    m_type = MediaType(media_type.lower())
    aggregator = StreamAggregator()

    with console.status(f"[bold cyan]Resolving stream {index} for {media_id}...[/bold cyan]"):
        streams = aggregator.aggregate_streams(media_type=m_type, media_id=media_id, season=season, episode=episode)
        sorted_streams = aggregator.sort_streams(streams, sort_by="quality")

    if not sorted_streams:
        console.print("[red]No stream sources found.[/red]")
        return

    if index < 1 or index > len(sorted_streams):
        console.print(f"[red]Invalid stream index {index}. Available: 1 to {len(sorted_streams)}[/red]")
        return

    target_stream = sorted_streams[index - 1]
    if not target_stream.is_torrent:
        console.print("[yellow]Selected stream is not a BitTorrent source (Direct HTTP or Debrid).[/yellow]")
        if target_stream.url:
            console.print(f"[bold green]Direct URL:[/bold green] {target_stream.url}")
        return

    magnet_uri = target_stream.build_magnet_uri()
    console.print(f"\n[bold green]Magnet URI:[/bold green]")
    console.print(f"[cyan]{magnet_uri}[/cyan]\n")
    console.print(f"[bold yellow]InfoHash:[/bold yellow] {target_stream.info_hash}")
    console.print(f"[bold yellow]File Index:[/bold yellow] {target_stream.file_idx}")


@cli.command("download")
@click.argument("media_id")
@click.option("--season", "-s", type=int, default=None, help="TV season number.")
@click.option("--episode", "-e", type=int, default=None, help="TV episode number.")
@click.option(
    "--type",
    "-t",
    "media_type",
    type=click.Choice(["movie", "series", "anime"], case_sensitive=False),
    default="movie",
    help="Media category.",
)
@click.option("--index", "-i", type=int, default=1, help="1-based stream index from streams table.")
@click.option("--dest-dir", "-d", type=click.Path(), default=None, help="Target download directory.")
def download_cmd(
    media_id: str,
    season: Optional[int],
    episode: Optional[int],
    media_type: str,
    index: int,
    dest_dir: Optional[str],
) -> None:
    """📥 Download media via HTTP stream or save/dispatch Magnet link."""
    m_type = MediaType(media_type.lower())
    aggregator = StreamAggregator()
    manager = DownloadManager(download_dir=dest_dir)

    with console.status(f"[bold cyan]Finding streams for {media_id}...[/bold cyan]"):
        streams = aggregator.aggregate_streams(media_type=m_type, media_id=media_id, season=season, episode=episode)
        sorted_streams = aggregator.sort_streams(streams, sort_by="quality")

    if not sorted_streams:
        console.print("[red]No stream sources found to download.[/red]")
        return

    if index < 1 or index > len(sorted_streams):
        console.print(f"[red]Invalid stream index {index}. Available: 1 to {len(sorted_streams)}[/red]")
        return

    target_stream = sorted_streams[index - 1]
    storage = StorageManager()
    media_item = storage.get_media_item(media_id)
    title = media_item.title if media_item else media_id
    if season and episode:
        title = f"{title} S{season:02d}E{episode:02d}"

    console.print(f"[bold green]Starting transfer for:[/bold green] {title}")
    console.print(f"[cyan]Selected Stream:[/cyan] {target_stream.release_title or target_stream.title}")

    if target_stream.is_http:
        progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        )
        task_id = progress.add_task("Downloading", total=target_stream.size_bytes or 0)

        def on_progress(rec) -> None:
            progress.update(task_id, completed=rec.downloaded_bytes, total=rec.total_bytes)

        with progress:
            rec = manager.download_source(
                stream=target_stream,
                media_id=media_id,
                media_title=title,
                progress_callback=on_progress,
            )

        console.print(f"[bold green]✓ Download finished:[/bold green] {rec.local_path}")

    elif target_stream.is_torrent:
        rec = manager.download_source(
            stream=target_stream,
            media_id=media_id,
            media_title=title,
        )
        console.print(f"[bold green]✓ Torrent processed:[/bold green]")
        console.print(f"  Status: [cyan]{rec.status.value}[/cyan]")
        console.print(f"  Magnet File: [yellow]{rec.local_path}[/yellow]")
        if rec.error_message:
            console.print(f"  Notice: [dim]{rec.error_message}[/dim]")


@cli.command("history")
@click.option("--limit", "-n", type=int, default=20, help="Number of records to show.")
@click.option(
    "--status",
    type=click.Choice(["pending", "downloading", "completed", "failed", "cancelled"], case_sensitive=False),
    default=None,
    help="Filter by status.",
)
def history_cmd(limit: int, status: Optional[str]) -> None:
    """📜 Display download history and local record logs."""
    manager = DownloadManager()
    records = manager.list_history(limit=limit)
    if status:
        records = [r for r in records if r.status.value == status.lower()]
    display_download_history(records)


@cli.group("addons")
def addons_group() -> None:
    """🔌 Manage registered Stremio Add-on providers."""
    pass


@addons_group.command("list")
def addons_list_cmd() -> None:
    """List all registered providers."""
    storage = StorageManager()
    addons = storage.get_addons()
    display_addons_table(addons)


@addons_group.command("add")
@click.argument("url")
@click.option("--priority", "-p", type=int, default=10, help="Execution priority (lower runs earlier).")
def addons_add_cmd(url: str, priority: int) -> None:
    """Register a new Stremio Add-on by its manifest or host URL."""
    registry = ProviderRegistry()
    success, msg, _ = registry.register_addon_by_url(url, priority=priority)
    if success:
        console.print(f"[bold green]✓ {msg}[/bold green]")
    else:
        console.print(f"[bold red]✗ {msg}[/bold red]")


@addons_group.command("toggle")
@click.argument("addon_id")
@click.option("--enable/--disable", default=True, help="Toggle addon status.")
def addons_toggle_cmd(addon_id: str, enable: bool) -> None:
    """Enable or disable an add-on provider."""
    storage = StorageManager()
    ok = storage.set_addon_enabled(addon_id, enable)
    if ok:
        status_word = "enabled" if enable else "disabled"
        console.print(f"[green]Addon '{addon_id}' is now {status_word}.[/green]")
    else:
        console.print(f"[red]Addon '{addon_id}' not found.[/red]")


@addons_group.command("remove")
@click.argument("addon_id")
def addons_remove_cmd(addon_id: str) -> None:
    """Remove an add-on provider from registry."""
    storage = StorageManager()
    ok = storage.delete_addon(addon_id)
    if ok:
        console.print(f"[green]Removed addon '{addon_id}'.[/green]")
    else:
        console.print(f"[red]Addon '{addon_id}' not found.[/red]")


@cli.command("config-torrentio")
@click.option("--providers", help="Comma-separated providers (e.g. yts,1337x,rarbg).")
@click.option("--sort", type=click.Choice(["qualitysize", "seeders", "size"]), default=None)
@click.option("--qualityfilter", help="Comma-separated quality filter (e.g. cam,scr).")
@click.option("--limit", type=int, help="Max streams per quality.")
@click.option("--debrid", help="Debrid provider (e.g. realdebrid, alldebrid, torbox).")
@click.option("--api-key", help="Debrid API key.")
def config_torrentio_cmd(
    providers: Optional[str],
    sort: Optional[str],
    qualityfilter: Optional[str],
    limit: Optional[int],
    debrid: Optional[str],
    api_key: Optional[str],
) -> None:
    """⚙️ Customize Torrentio providers, ranking, and debrid settings."""
    storage = StorageManager()
    addons = storage.get_addons()
    t_addon = None
    for a in addons:
        if "torrentio" in a.id.lower():
            t_addon = a
            break

    if not t_addon:
        console.print("[red]Torrentio addon is not registered.[/red]")
        return

    opts = t_addon.config_options or {}
    if providers is not None:
        opts["providers"] = [p.strip() for p in providers.split(",") if p.strip()]
    if sort is not None:
        opts["sort"] = sort
    if qualityfilter is not None:
        opts["qualityfilter"] = [q.strip() for q in qualityfilter.split(",") if q.strip()]
    if limit is not None:
        opts["limit"] = limit
    if debrid is not None:
        opts["debrid_provider"] = debrid
    if api_key is not None:
        opts["debrid_api_key"] = api_key

    t_addon.config_options = opts
    storage.save_addon(t_addon)
    console.print("[bold green]✓ Successfully updated Torrentio configuration.[/bold green]")


@cli.command("bot")
@click.option("--token", help="Telegram Bot Token (or set TELEGRAM_BOT_TOKEN).")
@click.option("--admin", type=int, help="Initial Telegram Administrator User ID.")
@click.option("--download-dir", help="Directory for storing downloaded media files.")
def bot_cmd(
    token: Optional[str],
    admin: Optional[int],
    download_dir: Optional[str],
) -> None:
    """🤖 Launch the Media Aggregator Telegram Bot."""
    import asyncio
    from media_aggregator.bot.app import run_bot
    from media_aggregator.bot.config import BotConfig

    cfg = BotConfig.from_env(token=token, admin_id=admin, download_dir=download_dir)
    if not cfg.bot_token:
        console.print(
            "[bold red]Error:[/bold red] No Telegram Bot Token specified.\n"
            "Provide --token or set the [bold]TELEGRAM_BOT_TOKEN[/bold] environment variable."
        )
        raise click.Abort()

    console.print("[bold cyan]Starting Media Aggregator Telegram Bot...[/bold cyan]")
    if cfg.admin_ids:
        console.print(f"[green]Configured Admins:[/green] {cfg.admin_ids}")
    else:
        console.print("[yellow]No admins pre-configured. First-time setup wizard will activate on /start.[/yellow]")
    console.print(f"[green]Download Directory:[/green] {cfg.download_dir}")

    try:
        asyncio.run(run_bot(cfg))
    except (KeyboardInterrupt, SystemExit):
        console.print("\n[yellow]Bot stopped by user.[/yellow]")
    except Exception as e:
        console.print(f"[bold red]Bot encountered fatal error:[/bold red] {e}")
        raise click.Abort()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
