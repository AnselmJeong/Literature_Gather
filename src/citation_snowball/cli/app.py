"""Citation Snowball CLI application - Directory-based project structure."""
import asyncio
import shutil
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from citation_snowball.config import (
    DATABASE_FILE_NAME,
    DOWNLOADS_DIR_NAME,
    SNOWBALL_DIR_NAME,
    ensure_project_dirs,
)
from citation_snowball.core.models import (
    DiscoveryMethod,
    DownloadStatus,
    IterationMode,
    Paper,
    Project,
)
from citation_snowball.db.database import Database
from citation_snowball.db.repository import (
    IterationRepository,
    PaperRepository,
    ProjectRepository,
)
from citation_snowball.export.html_report import HTMLReportGenerator
from citation_snowball.services.crossref import CrossrefClient
from citation_snowball.services.downloader import PDFDownloader
from citation_snowball.services.openalex import OpenAlexClient
from citation_snowball.services.pdf_parser import PDFParser
from citation_snowball.snowball.engine import SnowballEngine

app = typer.Typer(
    name="snowball",
    help="Citation Snowball - Academic reference discovery tool",
    add_completion=False,
)
console = Console(force_terminal=True)


def get_project_directory(directory: Path) -> Path:
    """Get the .snowball directory for the given directory."""
    return directory / SNOWBALL_DIR_NAME


def ensure_db_initialized(directory: Path) -> Database:
    """Ensure database is initialized for the given directory."""
    ensure_project_dirs(directory)
    return Database(directory)


def _load_project_or_exit(
    directory: Path,
    *,
    require_papers: bool = False,
) -> tuple[Database, Project, PaperRepository]:
    """Load project context for commands that require an existing run."""
    project_dir = get_project_directory(directory)
    if not project_dir.exists():
        console.print(f"[red]No project found in {directory}[/red]")
        console.print("[yellow]Run 'snowball expand' (or 'snowball run') first.[/yellow]")
        raise typer.Exit(1)

    db = Database(directory)
    project_repo = ProjectRepository(db)
    paper_repo = PaperRepository(db)
    project = project_repo.get_by_name(directory.name)

    if not project:
        console.print(f"[red]Project metadata not found in {project_dir}.[/red]")
        console.print("[yellow]Run 'snowball expand' (or 'snowball run') first.[/yellow]")
        raise typer.Exit(1)

    if require_papers and paper_repo.count(project.id) == 0:
        console.print("[red]No collected papers found for this project.[/red]")
        console.print("[yellow]Run 'snowball expand' (or 'snowball run') first.[/yellow]")
        raise typer.Exit(1)

    return db, project, paper_repo


def _parse_keywords_csv(raw: str | None) -> list[str]:
    """Parse comma-separated keywords into a normalized list."""
    if not raw:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]


def _normalize_keywords_option_values(values: list[str] | None) -> list[str]:
    """Normalize --keywords values, allowing comma-separated input per item."""
    if not values:
        return []
    normalized: list[str] = []
    for item in values:
        normalized.extend(_parse_keywords_csv(item))
    # De-duplicate while preserving order.
    return list(dict.fromkeys(normalized))


def _confirm_run_options(
    no_recursion: int | None, keywords: list[str] | None
) -> tuple[int, list[str]]:
    """Confirm required run options via InquirerPy in interactive terminals."""
    effective_no_recursion = no_recursion if no_recursion is not None else 1
    effective_keywords = _normalize_keywords_option_values(keywords)

    # In non-interactive environments, keep deterministic behavior.
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return effective_no_recursion, effective_keywords

    try:
        from InquirerPy import inquirer
    except Exception:
        # Fallback: still confirm in terminal without optional dependency.
        raw_keywords = typer.prompt(
            "Keywords (comma-separated, blank for none)",
            default=",".join(effective_keywords),
            show_default=True,
        )
        confirmed_no_recursion = typer.prompt(
            "--no-recursion value",
            default=effective_no_recursion,
            type=int,
            show_default=True,
        )
        return confirmed_no_recursion, _parse_keywords_csv(raw_keywords)

    try:
        raw_keywords = inquirer.text(
            message="Keywords (comma-separated, blank for none):",
            default=",".join(effective_keywords),
        ).execute()
        confirmed_no_recursion = inquirer.number(
            message="--no-recursion value:",
            default=str(effective_no_recursion),
            min_allowed=1,
            float_allowed=False,
        ).execute()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled by user.[/yellow]")
        raise typer.Exit(1)

    return int(confirmed_no_recursion), _parse_keywords_csv(raw_keywords)


def _precheck_run_directory(directory: Path, resume: bool) -> None:
    """Validate run/expand preconditions and handle existing project confirmation."""
    if not directory.exists():
        console.print(f"[red]Directory not found: {directory}[/red]")
        raise typer.Exit(1)

    project_dir = get_project_directory(directory)
    pdf_files = list(directory.glob("*.pdf"))

    # Check if project already exists
    if project_dir.exists():
        # Early guard: if there are no PDFs and no imported seeds, fail fast.
        if not pdf_files:
            db = ensure_db_initialized(directory)
            project_repo = ProjectRepository(db)
            paper_repo = PaperRepository(db)
            project = project_repo.get_by_name(directory.name)
            seed_count = len(paper_repo.list_seeds(project.id)) if project else 0
            if seed_count == 0:
                console.print(
                    "[red]No PDF files found in this directory and no existing seed papers in project data.[/red]"
                )
                console.print(
                    "[yellow]Add at least one PDF to the directory, then run again.[/yellow]"
                )
                raise typer.Exit(1)
        if resume:
            console.print(f"[yellow]Resuming existing project in {directory}[/yellow]")
        elif not typer.confirm(
            "Project already exists in .snowball/. Continue with existing data?",
            default=True,
        ):
            console.print("Cancelled.")
            raise typer.Exit(0)
    else:
        if not pdf_files:
            console.print("[red]No PDF files found in this directory.[/red]")
            console.print("[yellow]Add at least one PDF, then run again.[/yellow]")
            raise typer.Exit(1)
        console.print(f"[green]Creating new project in {directory}[/green]")


# ============================================================================
# Main Command: run
# ============================================================================


@app.command()
def run(
    directory: Path = typer.Argument(
        Path.cwd(),
        help="Directory containing PDF files (default: current directory)",
    ),
    max_iterations: int = typer.Option(
        None,
        "--max-iterations",
        "-n",
        help="Maximum number of iterations",
    ),
    no_recursion: int = typer.Option(
        1,
        "--no-recursion",
        help="Number of recursive expansion rounds",
    ),
    mode: IterationMode = typer.Option(
        None,
        "--mode",
        "-m",
        help="Iteration mode",
    ),
    no_download: bool = typer.Option(
        False,
        "--no-download",
        help="Skip PDF download",
    ),
    no_export: bool = typer.Option(
        False,
        "--no-export",
        help="Skip report export",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        "-r",
        help="Resume from existing project",
    ),
    keywords: list[str] = typer.Option(
        None,
        "--keywords",
        "-k",
        help="Filter papers by keywords (case-insensitive)",
    ),
) -> None:
    """Run snowballing on PDF directory.

    This command automatically:
    1. Creates a project in .snowball/ directory
    2. Imports PDFs from the directory as seed papers
    3. Runs the snowballing process
    4. Downloads available PDFs (unless --no-download)
    5. Exports reports (unless --no-export)

    Example:
        snowball run                    # Run in current directory
        snowball run ./my-papers        # Run in specific directory
        snowball run --max-iterations 3  # With options
    """
    # Mandatory run-time confirmation for keyword/no-recursion options.
    no_recursion, keywords = _confirm_run_options(no_recursion, keywords)
    _precheck_run_directory(directory, resume)

    # Run the full workflow
    asyncio.run(
        _run_async(
            directory,
            max_iterations,
            no_recursion,
            mode,
            no_download,
            no_export,
            keywords,
        )
    )


@app.command()
def expand(
    directory: Path = typer.Argument(
        Path.cwd(),
        help="Directory containing PDF files (default: current directory)",
    ),
    max_iterations: int = typer.Option(
        None,
        "--max-iterations",
        "-n",
        help="Maximum number of iterations",
    ),
    no_recursion: int = typer.Option(
        1,
        "--no-recursion",
        help="Number of recursive expansion rounds",
    ),
    mode: IterationMode = typer.Option(
        None,
        "--mode",
        "-m",
        help="Iteration mode",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        "-r",
        help="Resume from existing project",
    ),
    keywords: list[str] = typer.Option(
        None,
        "--keywords",
        "-k",
        help="Filter papers by keywords (case-insensitive)",
    ),
) -> None:
    """Run expansion only (import seeds + snowball), without download/export."""
    no_recursion, keywords = _confirm_run_options(no_recursion, keywords)
    _precheck_run_directory(directory, resume)

    asyncio.run(
        _run_async(
            directory,
            max_iterations,
            no_recursion,
            mode,
            True,   # no_download
            True,   # no_export
            keywords,
        )
    )


async def _run_async(
    directory: Path,
    max_iterations: Optional[int],
    no_recursion: Optional[int],
    mode: Optional[IterationMode],
    no_download: bool,
    no_export: bool,
    keywords: list[str] | None = None,
) -> None:
    """Async implementation of run command."""
    # Initialize database and project
    db = ensure_db_initialized(directory)
    project_repo = ProjectRepository(db)
    paper_repo = PaperRepository(db)

    # Get or create project
    project = project_repo.get_by_name(directory.name)
    if not project:
        project = project_repo.create(directory.name)

    # Override config if specified
    if max_iterations:
        project.config.max_iterations = max_iterations
    if no_recursion:
        project.config.no_recursion = no_recursion
    if mode:
        project.config.iteration_mode = mode
    if keywords:
        project.config.include_keywords = keywords
        console.print(f"[cyan]Filtering by keywords: {', '.join(keywords)}[/cyan]")

    # Check if seeds exist
    seeds = paper_repo.list_seeds(project.id)
    if not seeds:
        console.print("\n[cyan]Importing seed papers from PDFs...[/cyan]")
        await _import_seeds_async(directory, project, db, paper_repo)
        seeds = paper_repo.list_seeds(project.id)

    if not seeds:
        console.print("[yellow]No seed papers found. Check that PDFs are in the directory.[/yellow]")
        raise typer.Exit(1)

    # Run snowballing
    console.print("\n[cyan]Running snowballing process...[/cyan]")
    iteration_repo = IterationRepository(db)

    final_metrics = await _snowball_async(
        directory, project, db, paper_repo, iteration_repo
    )

    if not no_download:
        console.print("\n[cyan]Downloading PDFs...[/cyan]")
        output_dir = get_project_directory(directory) / DOWNLOADS_DIR_NAME
        await _download_async(project, db, paper_repo, output_dir)

    if not no_export:
        console.print("\n[cyan]Exporting reports...[/cyan]")
        output_dir = get_project_directory(directory) / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)
        await _export_async(project, db, paper_repo, iteration_repo, output_dir)

    # Show summary
    console.print("\n[green]=== Run Complete ===[/green]")
    console.print(f"Directory: {directory}")
    console.print(f"Project data: {get_project_directory(directory)}")
    if final_metrics:
        console.print(f"Total papers: {final_metrics['papers_after']}")
        console.print(f"Iterations: {final_metrics['iteration_number']}")


# ============================================================================
# Import Seeds
# ============================================================================


async def _import_seeds_async(
    directory: Path, project: Project, db: Database, paper_repo: PaperRepository
) -> None:
    """Asynchronous seed import with parallel processing."""
    pdf_parser = PDFParser()
    api_client = OpenAlexClient(db=db)
    crossref_client = CrossrefClient()

    # Get existing seeds
    existing_seeds = paper_repo.list_seeds(project.id)
    existing_ids = {p.openalex_id for p in existing_seeds}

    # Find PDFs
    pdf_files = list(directory.glob("*.pdf"))

    if not pdf_files:
        console.print("[yellow]No PDF files found in directory.[/yellow]")
        return

    console.print(f"Found {len(pdf_files)} PDF file(s) to process. Starting sequential import for verification...")
    
    # Pre-fetch existing IDs to a set
    existing_ids = {p.openalex_id for p in existing_seeds}

    imported = 0
    failed = 0
    skipped = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,  # Hide progress bar when printing logs
    ) as progress:
        task = progress.add_task("Importing seeds...", total=len(pdf_files))

        for idx, pdf_path in enumerate(pdf_files, 1):
            # Print log above the progress bar
            progress.stop()  # Pause progress bar to print cleanly
            console.print(f"\n[cyan][{idx}/{len(pdf_files)}] Processing: {pdf_path.name}[/cyan]")
            progress.start() # Resume progress bar

            try:
                # Step 1: Extract PDF metadata
                console.print("  [dim]→ Extracting PDF metadata...[/dim]")
                metadata = pdf_parser.extract_from_file(pdf_path)
                console.print(f"    DOI: {metadata.doi or '[not found]'}")
                console.print(f"    Title: {(metadata.title[:50] + '...') if metadata.title and len(metadata.title) > 50 else (metadata.title or '[not found]')}")

                # Try to resolve to OpenAlex
                work = None

                # Step 2: Search by DOI
                if metadata.doi:
                    console.print(f"  [dim]→ Searching OpenAlex by DOI: {metadata.doi}[/dim]")
                    work = await api_client.search_by_doi(metadata.doi)
                    if work:
                        console.print(f"    [green]Found via DOI![/green]")

                # Step 3: Search by title
                if not work and metadata.title:
                    console.print(f"  [dim]→ Searching OpenAlex by title...[/dim]")
                    work = await api_client.search_paper_by_title(metadata.title)
                    if work:
                        console.print(f"    [green]Found via title search![/green]")

                # Step 4: Fallback to Crossref
                if not work and metadata.title:
                    console.print(f"  [dim]→ Fallback: Searching Crossref by title...[/dim]")
                    crossref_results = await crossref_client.search_by_title(metadata.title)
                    if crossref_results:
                        doi = crossref_results[0].doi
                        if doi:
                            console.print(f"    Found DOI via Crossref: {doi}")
                            console.print(f"    Found DOI via Crossref: {doi}")
                            console.print(f"  [dim]→ Searching OpenAlex by Crossref DOI...[/dim]")
                            work = await api_client.search_by_doi(doi)
                            if work:
                                console.print(f"    [green]Found via Crossref DOI![/green]")

                if work:
                    # Check if already imported
                    if work.openalex_id in existing_ids:
                        console.print(f"  [yellow]Skipped (already imported)[/yellow]")
                        skipped += 1
                        progress.update(task, advance=1)
                        continue

                    import uuid
                    # Create seed paper with local_path and download_status set
                    paper = Paper(
                        id=str(uuid.uuid4()),
                        openalex_id=work.openalex_id,
                        doi=work.doi,
                        title=work.title or "",
                        authors=[a.author for a in work.authorships if a.author.display_name],
                        publication_year=work.publication_year,
                        journal=work.type,
                        abstract=work.abstract,
                        cited_by_count=work.cited_by_count,
                        counts_by_year=work.counts_by_year,
                        referenced_works=work.referenced_works,
                        discovery_method=DiscoveryMethod.SEED,
                        iteration_added=0,
                        # Mark as already downloaded since we have the local PDF
                        download_status=DownloadStatus.SUCCESS,
                        local_path=pdf_path,
                    )

                    paper_repo.create(project.id, paper)
                    imported += 1
                    console.print(f"  [green]✓ Imported: {work.title[:50]}...[/green]" if work.title and len(work.title) > 50 else f"  [green]✓ Imported: {work.title}[/green]")
                else:
                    failed += 1
                    console.print(f"  [red]✗ Could not resolve in OpenAlex[/red]")

            except Exception as e:
                failed += 1
                console.print(f"  [red]✗ Error: {e}[/red]")
            
            progress.update(task, advance=1)

    await api_client.close()
    await crossref_client.close()

    # Summary
    console.print(f"\n[green]Import complete![/green]")
    console.print(f"  Imported: {imported}")
    console.print(f"  Skipped: {skipped}")
    console.print(f"  Failed: {failed}")


# ============================================================================
# Snowballing
# ============================================================================


async def _snowball_async(
    directory: Path,
    project: Project,
    db: Database,
    paper_repo: PaperRepository,
    iteration_repo: IterationRepository,
) -> Optional[dict]:
    """Asynchronous snowballing."""
    from citation_snowball.config import get_settings

    settings = get_settings()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        async with OpenAlexClient(email=settings.openalex_api_key, db=db) as api_client:
            engine = SnowballEngine(
                project, api_client, paper_repo, iteration_repo, seed_directory=directory
            )

            task = progress.add_task("Snowballing...", total=None)

            async def progress_callback(iteration: int, metrics):
                progress.update(
                    task,
                    description=f"Iteration {iteration}: "
                    f"+{metrics.new_papers} papers (growth: {metrics.growth_rate:.1%})",
                )

            final_metrics = await engine.run(progress_callback=progress_callback)

    if final_metrics:
        console.print(f"\n[green]Snowballing complete![/green]")
        console.print(f"  Total papers: {final_metrics.papers_after}")
        console.print(f"  Iterations: {final_metrics.iteration_number}")
        console.print(f"  Final growth rate: {final_metrics.growth_rate:.1%}")
        return {
            "papers_after": final_metrics.papers_after,
            "iteration_number": final_metrics.iteration_number,
            "growth_rate": final_metrics.growth_rate,
        }
    else:
        console.print("[yellow]Snowballing stopped early.[/yellow]")
        return None


# ============================================================================
# Download PDFs
# ============================================================================


async def _download_async(
    project: Project, 
    db: Database, 
    paper_repo: PaperRepository, 
    output_dir: Path,
    retry_failed: bool = False
) -> None:
    """Asynchronous PDF download."""
    from citation_snowball.config import get_settings

    settings = get_settings()

    # Get papers
    all_papers = paper_repo.list_by_project(project.id)
    
    # Filter out papers that already have PDFs (e.g., seed papers)
    papers = [p for p in all_papers if not p.local_path]

    if not papers:
        console.print("[yellow]No papers to download (all papers already have PDFs).[/yellow]")
        return

    console.print(f"Downloading PDFs for {len(papers)} paper(s)... ({len(all_papers) - len(papers)} already downloaded)")
    downloader = PDFDownloader(
        paper_repo=paper_repo,
        output_dir=output_dir,
        api_key=settings.openalex_api_key,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading...", total=len(papers))

        async def progress_callback(completed: int, total: int, result, err_detail: str = ""):
            status = "[green]✓[/green]" if result.success else f"[red]✗{err_detail}[/red]"
            progress.update(
                task,
                description=f"{completed}/{total} {status}",
                advance=1,
            )

        download_results = await downloader.download_batch(
            papers,
            progress_callback=progress_callback,
            retry_failed=retry_failed,
        )

    stats = downloader.get_statistics()
    failed_results = [r for r in download_results if not r.success]
    if failed_results:
        report_path = output_dir.parent / "reports" / "download_failed_report.html"
        report_gen = HTMLReportGenerator()
        report_gen.generate_failure_report(download_results, papers, report_path)
        console.print(f"\n[yellow]Failure report generated:[/yellow] {report_path}")

    console.print(f"\n[green]Download complete![/green]")
    console.print(f"  Success: {stats['success']}")
    console.print(f"  Failed: {stats['failed']}")
    console.print(f"  Skipped: {stats['skipped']}")


# ============================================================================
# Export Reports
# ============================================================================


async def _export_async(
    project: Project,
    db: Database,
    paper_repo: PaperRepository,
    iteration_repo: IterationRepository,
    output_dir: Path,
) -> None:
    """Export results to HTML report."""
    papers = paper_repo.list_by_project(project.id)

    if not papers:
        console.print("[yellow]No papers to export.[/yellow]")
        return

    # Generate collection report
    iterations = iteration_repo.list_by_project(project.id)
    iteration_count = len(iterations)

    generator = HTMLReportGenerator()
    output_path = output_dir / f"{project.name}_report.html"
    generator.generate_collection_report(
        papers, project.name, iteration_count, output_path
    )
    console.print(f"[green]Report exported to: {output_path}[/green]")


# ============================================================================
# Results Command
# ============================================================================


@app.command()
def results(
    directory: Path = typer.Argument(
        Path.cwd(),
        help="Project directory (default: current directory)",
    ),
    sort_by: str = typer.Option(
        "score",
        "--sort",
        "-s",
        help="Sort by: score, year, citations, title",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of results to show",
    ),
) -> None:
    """Show collected papers for the current project.

    Example:
        snowball results                    # Show papers in current directory
        snowball results --sort year        # Sort by year
        snowball results --limit 20         # Show only top 20
    """
    _, project, paper_repo = _load_project_or_exit(directory, require_papers=True)

    # Get papers
    papers = paper_repo.list_by_project(
        project.id, sort_by=sort_by, descending=True, limit=limit
    )

    if not papers:
        console.print("[red]No papers found for display.[/red]")
        console.print("[yellow]Run 'snowball run' first.[/yellow]")
        raise typer.Exit(1)

    # Display table
    table = Table(title=f"Papers in '{directory.name}'")
    table.add_column("Score", style="cyan", justify="right")
    table.add_column("Title", style="white")
    table.add_column("Year", justify="right")
    table.add_column("Citations", justify="right")
    table.add_column("Method")
    table.add_column("DOI")

    for paper in papers:
        score_str = f"{paper.score:.2f}"
        if paper.score >= 0.7:
            score_str = f"[green]{score_str}[/green]"
        elif paper.score >= 0.4:
            score_str = f"[yellow]{score_str}[/yellow]"
        else:
            score_str = f"[red]{score_str}[/red]"

        doi_display = paper.doi[:40] + "..." if paper.doi and len(paper.doi) > 40 else (paper.doi or "-")
        title_display = paper.title[:60] + "..." if paper.title and len(paper.title) > 60 else (paper.title or "")

        table.add_row(
            score_str,
            title_display,
            str(paper.publication_year or "-"),
            str(paper.cited_by_count),
            paper.discovery_method.value,
            doi_display,
        )

    console.print(table)


# ============================================================================
# Download Command
# ============================================================================


@app.command()
def download(
    directory: Path = typer.Argument(
        Path.cwd(),
        help="Project directory (default: current directory)",
    ),
    retry_failed: bool = typer.Option(
        False,
        "--retry-failed",
        "-r",
        help="Retry previously failed downloads",
    ),
) -> None:
    """Download PDFs for collected papers.

    Example:
        snowball download                    # Download for current project
        snowball download --retry-failed     # Retry failed downloads
    """
    db, project, paper_repo = _load_project_or_exit(directory, require_papers=True)
    project_dir = get_project_directory(directory)
    output_dir = project_dir / DOWNLOADS_DIR_NAME
    asyncio.run(_download_async(project, db, paper_repo, output_dir, retry_failed))


# ============================================================================
# Export Command
# ============================================================================


@app.command()
def export(
    directory: Path = typer.Argument(
        Path.cwd(),
        help="Project directory (default: current directory)",
    ),
) -> None:
    """Export results to HTML report.

    Example:
        snowball export                     # Export for current project
        snowball export --directory ./my-papers
    """
    db, project, paper_repo = _load_project_or_exit(directory, require_papers=True)
    iteration_repo = IterationRepository(db)
    project_dir = get_project_directory(directory)
    output_dir = project_dir / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    asyncio.run(_export_async(project, db, paper_repo, iteration_repo, output_dir))


# ============================================================================
# Reset Command
# ============================================================================


@app.command()
def reset(
    directory: Path = typer.Argument(
        Path.cwd(),
        help="Project directory (default: current directory)",
    ),
) -> None:
    """Delete .snowball directory to start fresh.

    Example:
        snowball reset                      # Reset current project
        snowball reset --directory ./my-papers
    """
    project_dir = get_project_directory(directory)

    if not project_dir.exists():
        console.print(f"[yellow]No project found in {directory}[/yellow]")
        return

    if typer.confirm(f"Delete {project_dir}? This cannot be undone."):
        shutil.rmtree(project_dir)
        console.print(f"[green]Project data deleted from {directory}[/green]")


# ============================================================================
# Info Command
# ============================================================================


@app.command()
def info(
    directory: Path = typer.Argument(
        Path.cwd(),
        help="Project directory (default: current directory)",
    ),
) -> None:
    """Show project information.

    Example:
        snowball info                       # Show current project info
        snowball info --directory ./my-papers
    """
    _, project, paper_repo = _load_project_or_exit(directory, require_papers=True)
    project_dir = get_project_directory(directory)

    paper_count = paper_repo.count(project.id)
    seed_count = len(paper_repo.list_seeds(project.id))

    # Create info panel
    info_text = f"""
[bold cyan]Project:[/bold cyan] {project.name}
[bold cyan]Location:[/bold cyan] {directory}

[bold cyan]Status:[/bold cyan] {'[green]Complete[/green]' if project.is_complete else '[yellow]In Progress[/yellow]'}
[bold cyan]Total Papers:[/bold cyan] {paper_count}
[bold cyan]Seed Papers:[/bold cyan] {seed_count}
[bold cyan]Iterations:[/bold cyan] {project.current_iteration}

[bold cyan]Configuration:[/bold cyan]
  Max Iterations: {project.config.max_iterations}
  Papers per Iteration: {project.config.papers_per_iteration}
  Growth Threshold: {project.config.growth_threshold:.1%}
  Novelty Threshold: {project.config.novelty_threshold:.1%}
  Iteration Mode: {project.config.iteration_mode.value}
"""

    console.print(Panel(info_text.strip(), title="[bold]Project Info[/bold]", border_style="cyan"))

    # Show directory structure
    db_file = project_dir / DATABASE_FILE_NAME
    downloads_dir = project_dir / DOWNLOADS_DIR_NAME
    reports_dir = project_dir / "reports"

    console.print("\n[bold cyan]Project Files:[/bold cyan]")
    console.print(f"  Database: {db_file} ({db_file.stat().st_size // 1024} KB)" if db_file.exists() else "  Database: [red]Not found[/red]")
    console.print(f"  Downloads: {downloads_dir} ({len(list(downloads_dir.glob('*.pdf')))} PDFs)" if downloads_dir.exists() else f"  Downloads: [yellow]Not created[/yellow]")
    console.print(f"  Reports: {reports_dir}" if reports_dir.exists() else f"  Reports: [yellow]Not created[/yellow]")


if __name__ == "__main__":
    app()
