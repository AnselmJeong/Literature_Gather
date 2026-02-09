"""OpenAlex PDF Downloader CLI."""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import click
import requests
from tqdm import tqdm

API_BASE = "https://api.openalex.org"
CONTENT_BASE = "https://content.openalex.org"
DOWNLOAD_DIR = Path("./downloads")
OPENALEX_API_KEY = os.environ.get("OPENALEX_API_KEY")


def get_work(openalex_id: str | None = None, doi: str | None = None) -> dict | None:
    """Fetch work metadata from OpenAlex API."""
    if openalex_id:
        clean_id = openalex_id.replace("https://openalex.org/", "").strip()
        url = f"{API_BASE}/works/{clean_id}"
    elif doi:
        clean_doi = doi.strip()
        if not clean_doi.startswith("https://"):
            clean_doi = f"https://doi.org/{clean_doi}"
        url = f"{API_BASE}/works/{quote(clean_doi, safe='')}"
    else:
        return None

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        click.echo(f"Error fetching work: {exc}", err=True)
        return None


def extract_authors(authorships: list) -> str:
    """Extract compact author string for filename."""
    if not authorships:
        return "Unknown"

    authors = []
    for auth in authorships:
        author_info = auth.get("author", {})
        display_name = author_info.get("display_name", "")
        if display_name:
            parts = display_name.split()
            if parts:
                authors.append(parts[-1])

    if not authors:
        return "Unknown"
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]}, {authors[1]}"
    return f"{authors[0]} et al."


def format_title(title: str) -> tuple[str, str | None]:
    """Format title for filename."""
    title = title.replace(":", ";")
    if ";" in title:
        parts = title.split(";", 1)
        main_title = parts[0].strip()
        subtitle = parts[1].strip() if len(parts) > 1 else None
        return main_title, subtitle
    return title.strip(), None


def sanitize_filename(filename: str) -> str:
    """Remove filename-invalid chars and cap length."""
    filename = re.sub(r'[<>"/\\|?*]', "", filename)
    filename = re.sub(r"\s+", " ", filename)

    if len(filename) > 200:
        name, ext = filename.rsplit(".", 1)
        filename = f"{name[:195]}.{ext}"

    return filename.strip()


def generate_filename(work: dict) -> str:
    """Generate standardized filename."""
    year = work.get("publication_year", "Unknown")
    authors = extract_authors(work.get("authorships", []))
    main_title, subtitle = format_title(work.get("title", "Untitled"))

    if subtitle:
        filename = f"{year} - {authors} - {main_title}; {subtitle}.pdf"
    else:
        filename = f"{year} - {authors} - {main_title}.pdf"

    return sanitize_filename(filename)


def extract_openalex_id(work_id: str) -> str | None:
    """Extract OpenAlex ID (W123...) from URL-like value."""
    if not work_id:
        return None
    match = re.search(r"W\d+", work_id)
    return match.group(0) if match else None


def get_content_api_url(work_id: str) -> str | None:
    """Build OpenAlex Content API URL if key is configured."""
    if not OPENALEX_API_KEY:
        return None
    openalex_id = extract_openalex_id(work_id)
    if not openalex_id:
        return None
    return f"{CONTENT_BASE}/works/{openalex_id}.pdf"


def get_pdf_url(work: dict) -> tuple[str | None, str | None, bool]:
    """Return (pdf_url, landing_page_url, is_content_api)."""
    pdf_url: str | None = None
    landing_page: str | None = None

    content_url = get_content_api_url(work.get("id", ""))
    if content_url:
        return content_url, work.get("primary_location", {}).get("landing_page_url"), True

    best_oa = work.get("best_oa_location")
    if best_oa and isinstance(best_oa, dict):
        pdf_url = best_oa.get("pdf_url")
        landing_page = best_oa.get("landing_page_url")
        if pdf_url:
            return pdf_url, landing_page, False

    primary_loc = work.get("primary_location")
    if primary_loc and isinstance(primary_loc, dict):
        if not pdf_url:
            pdf_url = primary_loc.get("pdf_url")
        if not landing_page:
            landing_page = primary_loc.get("landing_page_url")
        if pdf_url:
            return pdf_url, landing_page, False

    for loc in work.get("locations", []):
        if isinstance(loc, dict):
            if not pdf_url:
                pdf_url = loc.get("pdf_url")
            if not landing_page:
                landing_page = loc.get("landing_page_url")
            if pdf_url:
                return pdf_url, landing_page, False

    return pdf_url, landing_page, False


def download_pdf(
    url: str,
    filepath: Path,
    timeout: int = 120,
    is_content_api: bool = False,
) -> bool:
    """Download PDF from URL to filepath."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/pdf,application/x-pdf,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if is_content_api and OPENALEX_API_KEY:
            headers["Authorization"] = f"Bearer {OPENALEX_API_KEY}"

        response = requests.get(url, stream=True, timeout=timeout, headers=headers)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        if "pdf" not in content_type and "application/octet-stream" not in content_type:
            if response.content[:4] != b"%PDF":
                click.echo(
                    f"Warning: Content may not be PDF (content-type: {content_type})",
                    err=True,
                )

        total_size = int(response.headers.get("content-length", 0))
        with filepath.open("wb") as file:
            if total_size > 0:
                with tqdm(
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    desc=filepath.name[:30],
                ) as pbar:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file.write(chunk)
                            pbar.update(len(chunk))
            else:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file.write(chunk)
        return True
    except requests.RequestException as exc:
        click.echo(f"Error downloading PDF: {exc}", err=True)
        return False
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Unexpected error: {exc}", err=True)
        return False


def parse_input_line(line: str) -> tuple[str | None, str | None]:
    """Parse line into (openalex_id, doi)."""
    line = line.strip()
    if not line:
        return None, None

    if line.lower().startswith("10.") or "doi.org" in line.lower():
        if "doi.org/" in line:
            line = line.split("doi.org/")[-1]
        return None, line

    if line.upper().startswith("W") or "openalex.org" in line.lower():
        if "openalex.org/" in line:
            line = line.split("openalex.org/")[-1]
        return line, None

    if line.upper().startswith("W"):
        return line, None
    return None, line


@click.command()
@click.argument("input_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    default=DOWNLOAD_DIR,
    help="Output directory for downloaded PDFs (default: ./downloads)",
)
@click.option(
    "--delay",
    "-d",
    type=float,
    default=0.5,
    help="Delay between requests in seconds (default: 0.5)",
)
@click.option(
    "--skip-existing/--no-skip-existing",
    "-s",
    default=True,
    help="Skip files that already exist (default: True)",
)
def main(input_file: Path, output_dir: Path, delay: float, skip_existing: bool) -> None:
    """Download PDFs from OpenAlex given a list of IDs or DOIs."""
    output_dir.mkdir(parents=True, exist_ok=True)

    lines = [line.strip() for line in input_file.read_text(encoding="utf-8").splitlines() if line.strip()]

    click.echo(f"Found {len(lines)} entries to process")
    click.echo(f"Output directory: {output_dir.absolute()}")
    click.echo("-" * 60)

    success_count = 0
    failed_count = 0
    skipped_count = 0

    for i, line in enumerate(lines, 1):
        click.echo(f"\n[{i}/{len(lines)}] Processing: {line[:60]}...")

        openalex_id, doi = parse_input_line(line)
        work = get_work(openalex_id=openalex_id, doi=doi)
        if not work:
            click.echo("  Failed to fetch metadata")
            failed_count += 1
            continue

        filename = generate_filename(work)
        filepath = output_dir / filename

        if skip_existing and filepath.exists():
            click.echo(f"  Already exists: {filename}")
            skipped_count += 1
            continue

        pdf_url, landing_page, is_content_api = get_pdf_url(work)
        oa_status = work.get("open_access", {}).get("oa_status", "unknown")

        if not pdf_url:
            if landing_page:
                click.echo(f"  No direct PDF available (OA status: {oa_status})")
                click.echo(f"  You can access the paper at: {landing_page}")
            else:
                click.echo(f"  No PDF or landing page available (OA status: {oa_status})")
            failed_count += 1
            continue

        click.echo(f"  Downloading: {filename}")
        click.echo("  Source: OpenAlex Content API" if is_content_api else f"  Source: {pdf_url[:60]}...")
        if landing_page and landing_page != pdf_url:
            click.echo(f"  Landing page: {landing_page[:60]}...")

        if download_pdf(pdf_url, filepath, is_content_api=is_content_api):
            click.echo(f"  \u2713 Saved to: {filepath}")
            success_count += 1
        else:
            if is_content_api:
                click.echo("  Content API failed, trying fallback...")
                best_oa = work.get("best_oa_location")
                if best_oa and isinstance(best_oa, dict):
                    fallback_pdf = best_oa.get("pdf_url")
                    if fallback_pdf:
                        click.echo(f"  Trying: {fallback_pdf[:60]}...")
                        if download_pdf(fallback_pdf, filepath, is_content_api=False):
                            click.echo(f"  \u2713 Saved to: {filepath}")
                            success_count += 1
                            continue

            click.echo("  \u2717 Failed to download")
            if landing_page:
                click.echo(f"    Try accessing manually: {landing_page}")
            failed_count += 1

        if i < len(lines) and delay > 0:
            time.sleep(delay)

    click.echo("\n" + "=" * 60)
    click.echo("SUMMARY")
    click.echo(f"  Total: {len(lines)}")
    click.echo(f"  Success: {success_count}")
    click.echo(f"  Failed: {failed_count}")
    click.echo(f"  Skipped (already exists): {skipped_count}")

    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

