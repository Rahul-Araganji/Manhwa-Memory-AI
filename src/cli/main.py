import os
import sys
import logging
from pathlib import Path
from typing import Optional

# Force UTF-8 encoding for standard input/output on Windows
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from src.config import Config
from src.database.db_manager import DatabaseManager
from src.downloader.downloader import DownloaderManager
from src.cleaner.image_cleaner import ImageCleaner
from src.ocr.ocr_engine import OcrEngine
from src.summarizer.ai_summarizer import AiSummarizer

# Define paths relative to the project directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Set up consoles
console = Console()

def setup_logging():
    log_dir = PROJECT_ROOT / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "manga_memory.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    # Lower third-party log noise
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)

@click.group()
def cli():
    """Manga Memory AI: Create persistent memory databases for your favorite Manga/Manhwa."""
    setup_logging()

def get_services(db: DatabaseManager) -> Optional[str]:
    """Helper to retrieve default series name if there's only one in the DB."""
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM series;")
        rows = cursor.fetchall()
        if len(rows) == 1:
            return rows[0]["name"]
    return None

@cli.command("download")
@click.option("--series", required=True, help="Name of the manga/manhwa series.")
@click.option("--url", required=True, help="URL of the series page.")
@click.option("--start", type=float, help="Start chapter number (inclusive).")
@click.option("--end", type=float, help="End chapter number (inclusive).")
def download_cmd(series: str, url: str, start: Optional[float], end: Optional[float]):
    """Download chapter images from a series URL."""
    config = Config()
    db = DatabaseManager(config.db_path)
    downloader = DownloaderManager(config, db)
    
    console.print(f"[bold blue]Starting download for '{series}'...[/bold blue]")
    try:
        downloaded = downloader.download_series(series, url, start, end)
        if downloaded:
            console.print(f"[bold green]Downloaded chapters: {downloaded}[/bold green]")
        else:
            console.print("[yellow]No new chapters downloaded.[/yellow]")
    except Exception as e:
        console.print(f"[bold red]Download failed: {e}[/bold red]")
        sys.exit(1)

@cli.command("clean")
@click.option("--series", help="Name of the series. If omitted, uses default.")
@click.option("--chapter", type=float, help="Specific chapter number to clean. Omit to clean all downloaded.")
def clean_cmd(series: Optional[str], chapter: Optional[float]):
    """Clean duplicate and credit pages from chapters."""
    config = Config()
    db = DatabaseManager(config.db_path)
    
    if not series:
        series = get_services(db)
        if not series:
            console.print("[bold red]Error: Series name is required (could not detect default).[/bold red]")
            sys.exit(1)

    cleaner = ImageCleaner(config, db)
    series_id = db.get_or_create_series(series)
    
    if chapter is not None:
        chapters = [db.get_chapter(series_id, chapter)]
        # Filter out None values
        chapters = [ch for ch in chapters if ch]
    else:
        # Get all downloaded chapters that are not cleaned yet
        chapters = db.get_chapters_by_status(series_id, "downloaded")

    if not chapters:
        console.print("[yellow]No chapters found to clean.[/yellow]")
        return

    console.print(f"[bold blue]Cleaning {len(chapters)} chapters for '{series}'...[/bold blue]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console
    ) as progress:
        task = progress.add_task("Cleaning chapters", total=len(chapters))
        for ch in chapters:
            ch_num = ch["chapter_num"]
            progress.update(task, description=f"Cleaning Chapter {ch_num}")
            cleaner.clean_chapter(series, ch_num)
            progress.advance(task)

@cli.command("ocr")
@click.option("--series", help="Name of the series.")
@click.option("--chapter", type=float, help="Specific chapter number to OCR. Omit to OCR all cleaned.")
def ocr_cmd(series: Optional[str], chapter: Optional[float]):
    """Extract text from chapter images using EasyOCR."""
    config = Config()
    db = DatabaseManager(config.db_path)

    if not series:
        series = get_services(db)
        if not series:
            console.print("[bold red]Error: Series name is required (could not detect default).[/bold red]")
            sys.exit(1)

    ocr_engine = OcrEngine(config, db)
    series_id = db.get_or_create_series(series)

    if chapter is not None:
        chapters = [db.get_chapter(series_id, chapter)]
        chapters = [ch for ch in chapters if ch and ch["status"] == "cleaned"]
    else:
        chapters = db.get_chapters_by_status(series_id, "cleaned")

    if not chapters:
        console.print("[yellow]No cleaned chapters found to run OCR on.[/yellow]")
        return

    console.print(f"[bold blue]Running OCR on {len(chapters)} chapters for '{series}'...[/bold blue]")
    # EasyOCR print initialization might output library text, which is fine
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console
    ) as progress:
        task = progress.add_task("Performing OCR", total=len(chapters))
        for ch in chapters:
            ch_num = ch["chapter_num"]
            progress.update(task, description=f"OCR Chapter {ch_num}")
            ocr_engine.ocr_chapter(series, ch_num)
            progress.advance(task)

@cli.command("summarize")
@click.option("--series", help="Name of the series.")
@click.option("--chapter", type=float, help="Specific chapter to summarize. Omit to summarize all OCR'd.")
def summarize_cmd(series: Optional[str], chapter: Optional[float]):
    """Summarize OCR'd chapters and generate Arc summaries using Gemini."""
    config = Config()
    db = DatabaseManager(config.db_path)

    if not series:
        series = get_services(db)
        if not series:
            console.print("[bold red]Error: Series name is required (could not detect default).[/bold red]")
            sys.exit(1)

    summarizer = AiSummarizer(config, db)
    series_id = db.get_or_create_series(series)

    if chapter is not None:
        chapters = [db.get_chapter(series_id, chapter)]
        chapters = [ch for ch in chapters if ch and ch["status"] == "ocr_completed"]
    else:
        chapters = db.get_chapters_by_status(series_id, "ocr_completed")

    if not chapters:
        console.print("[yellow]No chapters found waiting for summarization.[/yellow]")
        return

    console.print(f"[bold blue]Summarizing {len(chapters)} chapters for '{series}'...[/bold blue]")
    
    # Auto-summarize chapters
    for ch in chapters:
        ch_num = ch["chapter_num"]
        console.print(f"Summarizing Chapter {ch_num}...")
        summarizer.summarize_chapter(series, ch_num)
        
        # Check if we should trigger arc summarization
        check_and_trigger_arc_summaries(series, db, summarizer)

def check_and_trigger_arc_summaries(series_name: str, db: DatabaseManager, summarizer: AiSummarizer):
    """Automatically scans database and builds arc summaries every 20 chapters."""
    series_id = db.get_or_create_series(series_name)
    all_chapters = db.get_all_chapters(series_id)
    
    # We find groups of 20: 1 to 20, 21 to 40, etc.
    # Group ranges: (1, 20), (21, 40), (41, 60), etc.
    # To determine the maximum chapter, check database chapters
    if not all_chapters:
        return
        
    max_chapter_num = max(ch["chapter_num"] for ch in all_chapters)
    
    # Find all 20-chapter bounds
    # E.g. limit is max_chapter_num, step is 20
    # Let's generate intervals: (1, 20), (21, 40), (41, 60), ...
    interval_size = 20
    
    # We check each potential interval
    start = 1.0
    while start <= max_chapter_num:
        end = start + interval_size - 1
        
        # Check if there is already an arc summary in SQLite for this interval
        existing_arc = db.get_arc_summary(series_id, start, end)
        if not existing_arc:
            # Check if all chapters in this interval are summarized
            # First, check how many chapters are actually present in the DB in this range
            # Note: some chapters might be missing (e.g. if the series skips a number), 
            # so we check if all chapters in this range in the database have status 'summarized'
            ch_in_range = [
                ch for ch in all_chapters 
                if start <= ch["chapter_num"] <= end
            ]
            
            # We require that at least one chapter exists, and ALL chapters in this range are summarized
            if ch_in_range and all(ch["status"] == "summarized" for ch in ch_in_range):
                console.print(f"[bold magenta]Auto-generating Arc Summary for chapters {start} to {end}...[/bold magenta]")
                summarizer.summarize_arc(series_name, start, end)
                
        start += interval_size

@cli.command("pipeline")
@click.option("--series", required=True, help="Name of the manga/manhwa series.")
@click.option("--url", required=True, help="URL of the series page.")
@click.option("--start", type=float, help="Start chapter number (inclusive).")
@click.option("--end", type=float, help="End chapter number (inclusive).")
def pipeline_cmd(series: str, url: str, start: Optional[float], end: Optional[float]):
    """Run the entire automated pipeline (download -> clean -> ocr -> summarize)."""
    # 1. Download
    ctx = click.get_current_context()
    ctx.invoke(download_cmd, series=series, url=url, start=start, end=end)
    
    # 2. Clean
    ctx.invoke(clean_cmd, series=series, chapter=None)
    
    # 3. OCR
    ctx.invoke(ocr_cmd, series=series, chapter=None)
    
    # 4. Summarize
    ctx.invoke(summarize_cmd, series=series, chapter=None)
    
    console.print(f"[bold green]Pipeline successfully finished for '{series}'![/bold green]")

@cli.command("memory-refresh")
@click.argument("chapter_num", type=float)
@click.option("--series", help="Name of the series. If omitted, uses default.")
def refresh_cmd(chapter_num: float, series: Optional[str]):
    """Refresh your memory on the story up to CHAPTER_NUM."""
    config = Config()
    db = DatabaseManager(config.db_path)

    if not series:
        series = get_services(db)
        if not series:
            console.print("[bold red]Error: Series name is required (could not detect default).[/bold red]")
            sys.exit(1)

    summarizer = AiSummarizer(config, db)
    
    console.print(f"[bold blue]Generating Memory Refresh for '{series}' up to Chapter {chapter_num}...[/bold blue]")
    
    refresh_data = summarizer.generate_memory_refresh(series, chapter_num)
    if not refresh_data:
        console.print("[bold red]Could not generate memory refresh. Make sure chapters are downloaded, OCR'd, and summarized first.[/bold red]")
        sys.exit(1)

    # Output details in beautiful Rich formatting
    console.print("\n")
    console.print(Panel(
        f"[bold white]{refresh_data.get('story_so_far', '')}[/bold white]",
        title=f"[bold green]Story So Far (up to Chapter {chapter_num})[/bold green]",
        border_style="green",
        padding=(1, 2)
    ))
    
    # Print Main Characters Table
    char_table = Table(title="[bold blue]Main Characters[/bold blue]", border_style="blue", show_header=True)
    char_table.add_column("Character", style="bold cyan", width=20)
    char_table.add_column("Description", style="white")
    
    for char in refresh_data.get("main_characters", []):
        if isinstance(char, dict):
            char_table.add_row(char.get("name", "Unknown"), char.get("description", ""))
        else:
            char_table.add_row(str(char), "")
            
    console.print(char_table)
    
    # Print Relationships
    rel_panel_content = "\n".join([f"• {r}" for r in refresh_data.get("character_relationships", [])])
    console.print(Panel(
        rel_panel_content or "[dim]No key relationship updates.[/dim]",
        title="[bold cyan]Character Relationships[/bold cyan]",
        border_style="cyan",
        padding=(1, 2)
    ))

    # Print Reveals & Mysteries Side by Side
    reveals_str = "\n".join([f"• {rev}" for rev in refresh_data.get("important_reveals", [])])
    mysteries_str = "\n".join([f"• {mys}" for mys in refresh_data.get("unresolved_mysteries", [])])
    
    t_split = Table.grid(expand=True)
    t_split.add_column(ratio=1)
    t_split.add_column(ratio=1)
    t_split.add_row(
        Panel(reveals_str or "[dim]None yet.[/dim]", title="[bold yellow]Important Reveals[/bold yellow]", border_style="yellow"),
        Panel(mysteries_str or "[dim]None yet.[/dim]", title="[bold red]Unresolved Mysteries[/bold red]", border_style="red")
    )
    console.print(t_split)

    # Print Things to Remember
    next_ch = int(chapter_num) + 1 if chapter_num.is_integer() else chapter_num + 1
    remember_str = "\n".join([f"• {item}" for item in refresh_data.get("things_to_remember", [])])
    console.print(Panel(
        remember_str or "[dim]Nothing specific, enjoy reading![/dim]",
        title=f"[bold gold1]Things to Remember Before Chapter {next_ch}[/bold gold1]",
        border_style="gold1",
        padding=(1, 2)
    ))

if __name__ == "__main__":
    cli()
