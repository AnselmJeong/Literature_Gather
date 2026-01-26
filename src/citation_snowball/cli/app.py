"""Citation Snowball CLI application."""
import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from citation_snowball.config import get_settings
from citation_snowball.core.models import (
    IterationMode,
    Project,
    ProjectConfig,
    ScoringWeights,
)
from citation_snowball.db.database import Database
from citation_snowball.db.repository import IterationRepository, PaperRepository, ProjectRepository
from citation_snowball.export.html_report import HTMLReportGenerator
from citation_snowball.services.crossref import CrossrefClient
from citation_snowball.services.downloader import PDFDownloader
from citation_snowball.services.openalex import OpenAlexClient
from citation_snowball.services.pdf_parser import PDFParser
from citation_snowball.services.unpaywall import UnpaywallClient
from citation_snowball.snowball.engine import SnowballEngine

app = typer.Typer(
    name="snowball",
    help="Citation Snowball - Academic reference discovery tool",
    add_completion=False,
)
console = Console()


# ============================================================================
# Project Commands
# ============================================================================


@app.command()
def init(
    name: str = typer.Argument(..., help="Project name"),
    base_path: Path = typer.Option(
        Path.cwd(),
        "--path",
        "-p",
        help="Base directory for project data",
    ),
) -> None:
    """Initialize a new project.

    Creates a new Citation Snowball project with default configuration.
    """
    db = Database(base_path)
    project_repo = ProjectRepository(db)

    # Check if project already exists
    if project_repo.get_by_name(name):
        console.print(f"[red]Project '{name}' already exists![/red]")
        raise typer.Exit(1)

    # Create project
    project = project_repo.create(name)
    console.print(f"[green]Project '{name}' created successfully![/green]")
    console.print(f"  Project ID: {project.id}")


@app.command("list")
def list_projects() -> None:
    """List all projects."""
    db = Database()
    project_repo = ProjectRepository(db)

    projects = project_repo.list_all()

    if not projects:
        console.print("[yellow]No projects found.[/yellow]")
        return

    table = Table(title="Projects")
    table.add_column("Name", style="cyan")
    table.add_column("ID", style="dim")
    table.add_column("Papers", justify="right")
    table.add_column("Status", style="bold")
    table.add_column("Created", style="dim")

    paper_repo = PaperRepository(db)

    for project in projects:
        paper_count = paper_repo.count(project.id)
        status = "[green]Complete[/green]" if project.is_complete else "[yellow]In Progress[/yellow]"

        table.add_row(
            project.name,
            project.id[:8] + "...",
            str(paper_count),
            status,
            project.created_at.strftime("%Y-%m-%d"),
        )

    console.print(table)


@app.command()
def delete(project: str = typer.Argument(..., help="Project name or ID")) -> None:
    """Delete a project and all its data."""
    db = Database()
    project_repo = ProjectRepository(db)

    # Find project
    target = project_repo.get_by_name(project) or project_repo.get(project)

    if not target:
        console.print(f"[red]Project '{project}' not found![/red]")
        raise typer.Exit(1)

    # Confirm deletion
    if not typer.confirm(f"Delete project '{target.name}'? This cannot be undone."):
        console.print("Cancelled.")
        return

    project_repo.delete(target.id)
    console.print(f"[green]Project '{target.name}' deleted.[/green]")


# ============================================================================
# Seed Import Commands
# ============================================================================


@app.command()
def import_seeds(
    folder: Path = typer.Argument(..., help="Folder containing PDF files"),
    project: str = typer.Option(
        None,
        "--project",
        "-p",
        help="Project name or ID (uses default if not specified)",
    ),
) -> None:
    """Import seed papers from PDF files.

    Scans a folder for PDF files, extracts metadata, and resolves to OpenAlex works.
    """
    if not folder.exists():
        console.print(f"[red]Folder not found: {folder}[/red]")
        raise typer.Exit(1)

    # Get project
    db = Database()
    project_repo = ProjectRepository(db)

    if project:
        target = project_repo.get_by_name(project) or project_repo.get(project)
    else:
        projects = project_repo.list_all()
        if not projects:
            console.print("[red]No projects found. Create one with 'snowball init'.[/red]")
            raise typer.Exit(1)
        if len(projects) > 1:
            console.print("[yellow]Multiple projects found. Specify with --project.[/yellow]")
            list_projects()
            raise typer.Exit(1)
        target = projects[0]

    if not target:
        console.print(f"[red]Project '{project}' not found![/red]")
        raise typer.Exit(1)

    # Run import asynchronously
    asyncio.run(_import_seeds_async(folder, target))


async def _import_seeds_async(folder: Path, project: Project) -> None:
    """Asynchronous seed import."""
    pdf_parser = PDFParser()
    api_client = OpenAlexClient()
    crossref_client = CrossrefClient()
    paper_repo = PaperRepository(Database())

    # Get existing seeds
    existing_seeds = paper_repo.list_seeds(project.id)
    existing_ids = {p.openalex_id for p in existing_seeds}

    # Find PDFs
    pdf_files = list(folder.glob("*.pdf"))

    if not pdf_files:
        console.print("[yellow]No PDF files found in folder.[/yellow]")
        raise typer.Exit(0)

    console.print(f"Found {len(pdf_files)} PDF file(s) to process.")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Importing seeds...", total=len(pdf_files))

        imported = 0
        failed = 0
        skipped = 0

        for pdf_path in pdf_files:
            progress.update(task, description=f"Processing {pdf_path.name}...")

            try:
                # Extract metadata
                metadata = pdf_parser.extract_from_file(pdf_path)

                # Try to resolve to OpenAlex
                work = None

                if metadata.doi:
                    work = await api_client.search_by_doi(metadata.doi)

                if not work and metadata.title:
                    works_response = await api_client.search_by_title(metadata.title)
                    if works_response.results:
                        work = works_response.results[0]

                if not work and metadata.title:
                    # Fallback to Crossref
                    crossref_results = await crossref_client.search_by_title(metadata.title)
                    if crossref_results:
                        doi = crossref_results[0].doi
                        if doi:
                            work = await api_client.search_by_doi(doi)

                if work:
                    # Check if already imported
                    if work.openalex_id in existing_ids:
                        skipped += 1
                        continue

                    # Create seed paper
                    from citation_snowball.core.models import DiscoveryMethod, Paper

                    paper = Paper(
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
                    )

                    paper_repo.create(project.id, paper)
                    imported += 1
                else:
                    failed += 1
                    console.print(f"  [yellow]Could not resolve: {pdf_path.name}[/yellow]")

            except Exception as e:
                failed += 1
                console.print(f"  [red]Error processing {pdf_path.name}: {e}[/red]")

            progress.update(task, advance=1)

    await api_client.close()
    await crossref_client.close()

    # Summary
    console.print(f"\n[green]Import complete![/green]")
    console.print(f"  Imported: {imported}")
    console.print(f"  Skipped: {skipped}")
    console.print(f"  Failed: {failed}")


# ============================================================================
# Snowballing Commands
# ============================================================================


@app.command()
def snowball(
    project: str = typer.Argument(..., help="Project name or ID"),
    max_iterations: int = typer.Option(
        None,
        "--max-iterations",
        "-n",
        help="Maximum number of iterations (overrides config)",
    ),
    mode: IterationMode = typer.Option(
        None,
        "--mode",
        "-m",
        help="Iteration mode (overrides config)",
    ),
) -> None:
    """Run the snowballing process."""
    # Get project
    db = Database()
    project_repo = ProjectRepository(db)
    paper_repo = PaperRepository(db)
    iteration_repo = IterationRepository(db)

    target = project_repo.get_by_name(project) or project_repo.get(project)

    if not target:
        console.print(f"[red]Project '{project}' not found![/red]")
        raise typer.Exit(1)

    # Check if seeds exist
    seeds = paper_repo.list_seeds(target.id)
    if not seeds:
        console.print("[red]No seed papers found. Import seeds first with 'snowball import-seeds'.[/red]")
        raise typer.Exit(1)

    # Override config if specified
    if max_iterations:
        target.config.max_iterations = max_iterations
    if mode:
        target.config.iteration_mode = mode

    # Run snowballing
    asyncio.run(_snowball_async(target, paper_repo, iteration_repo))


async def _snowball_async(
    project: Project,
    paper_repo: PaperRepository,
    iteration_repo: IterationRepository,
) -> None:
    """Asynchronous snowballing."""
    settings = get_settings()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        async with OpenAlexClient(email=settings.openalex_api_key) as api_client:
            engine = SnowballEngine(project, api_client, paper_repo, iteration_repo)

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
    else:
        console.print("[yellow]Snowballing stopped early.[/yellow]")


# ============================================================================
# Results and Export Commands
# ============================================================================


@app.command()
def results(
    project: str = typer.Argument(..., help="Project name or ID"),
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
    """Show collected papers for a project."""
    db = Database()
    project_repo = ProjectRepository(db)
    paper_repo = PaperRepository(db)

    target = project_repo.get_by_name(project) or project_repo.get(project)

    if not target:
        console.print(f"[red]Project '{project}' not found![/red]")
        raise typer.Exit(1)

    # Get papers
    papers = paper_repo.list_by_project(
        target.id, sort_by=sort_by, descending=True, limit=limit
    )

    if not papers:
        console.print("[yellow]No papers found. Run snowballing first.[/yellow]")
        return

    # Display table
    table = Table(title=f"Papers in '{target.name}'")
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


@app.command()
def download(
    project: str = typer.Argument(..., help="Project name or ID"),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Output directory (uses project downloads if not specified)",
    ),
    select: str = typer.Option(
        "all",
        "--select",
        "-s",
        help="Selection: all, pending, success",
    ),
) -> None:
    """Download PDFs for collected papers."""
    db = Database()
    project_repo = ProjectRepository(db)
    paper_repo = PaperRepository(db)

    target = project_repo.get_by_name(project) or project_repo.get(project)

    if not target:
        console.print(f"[red]Project '{project}' not found![/red]")
        raise typer.Exit(1)

    # Get output directory
    if output is None:
        output = Database().db_path.parent.parent / "downloads"

    # Run download
    asyncio.run(_download_async(target, paper_repo, output, select))


async def _download_async(
    project: Project,
    paper_repo: PaperRepository,
    output_dir: Path,
    select: str,
) -> None:
    """Asynchronous PDF download."""
    settings = get_settings()

    # Get papers
    papers = paper_repo.list_by_project(project.id)
    if select == "pending":
        papers = [p for p in papers if p.download_status.value == "pending"]
    elif select == "success":
        papers = [p for p in papers if p.download_status.value == "success"]

    if not papers:
        console.print("[yellow]No papers to download.[/yellow]")
        return

    console.print(f"Downloading PDFs for {len(papers)} paper(s)...")

    async with UnpaywallClient(email=settings.openalex_api_key) as unpaywall:
        downloader = PDFDownloader(unpaywall, paper_repo, output_dir)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading...", total=len(papers))

            async def progress_callback(
                completed: int, total: int, result
            ):
                status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
                progress.update(
                    task,
                    description=f"{completed}/{total} {status}",
                    advance=1,
                )

            await downloader.download_batch(papers, progress_callback=progress_callback)

    # Show statistics
    stats = downloader.get_statistics()
    console.print(f"\n[green]Download complete![/green]")
    console.print(f"  Success: {stats['success']}")
    console.print(f"  Failed: {stats['failed']}")
    console.print(f"  Skipped: {stats['skipped']}")


@app.command()
def export(
    project: str = typer.Argument(..., help="Project name or ID"),
    format: str = typer.Option(
        "html",
        "--format",
        "-f",
        help="Export format: html, collection",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (auto-generated if not specified)",
    ),
) -> None:
    """Export results to file."""
    db = Database()
    project_repo = ProjectRepository(db)
    paper_repo = PaperRepository(db)

    target = project_repo.get_by_name(project) or project_repo.get(project)

    if not target:
        console.print(f"[red]Project '{project}' not found![/red]")
        raise typer.Exit(1)

    # Get papers
    papers = paper_repo.list_by_project(target.id)

    if not papers:
        console.print("[yellow]No papers to export.[/yellow]")
        return

    # Generate output path if not specified
    if output is None:
        output = Database().db_path.parent.parent / "reports"
        output.mkdir(parents=True, exist_ok=True)
        if format == "html":
            output = output / "download_report.html"
        else:
            output = output / "collection_report.html"

    # Generate report
    generator = HTMLReportGenerator()

    if format == "html":
        # Download report requires download results from download command
        console.print("[yellow]Download report generation requires download results.[/yellow]")
        console.print("[yellow]Use 'snowball download' first, then export will generate download report.[/yellow]")
    else:
        # Collection report
        iterations = IterationRepository(db).list_by_project(target.id)
        iteration_count = len(iterations)
        generator.generate_collection_report(papers, target.name, iteration_count, output)
        console.print(f"[green]Collection report exported to: {output}[/green]")


if __name__ == "__main__":
    app()