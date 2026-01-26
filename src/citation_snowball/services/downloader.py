"""PDF download service using Unpaywall."""
import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING

from citation_snowball.core.models import DownloadResult, DownloadStatus, Paper
from citation_snowball.db.repository import PaperRepository
from citation_snowball.services.unpaywall import UnpaywallClient

if TYPE_CHECKING:
    pass


def sanitize_filename(name: str, max_length: int = 100) -> str:
    """Sanitize a string for use as a filename.

    Args:
        name: String to sanitize
        max_length: Maximum length for filename

    Returns:
        Sanitized filename string
    """
    # Remove/replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", name)
    sanitized = sanitized.strip()

    # Remove leading/trailing dots and spaces
    sanitized = sanitized.strip(". ")

    # Truncate to max length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rsplit(" ", 1)[0]

    return sanitized or "unnamed"


def generate_pdf_filename(paper: Paper) -> str:
    """Generate a filename for a PDF.

    Format: {year}_{first_author}_{short_title}.pdf

    Args:
        paper: Paper to generate filename for

    Returns:
        Filename string
    """
    # Year
    year = str(paper.publication_year) if paper.publication_year else "unknown"

    # First author
    first_author = "unknown"
    if paper.authors:
        author_name = paper.authors[0].display_name
        # Get last name (part after last space)
        parts = author_name.split()
        if parts:
            first_author = parts[-1]

    # Short title (first few words)
    short_title = "title"
    if paper.title:
        words = paper.title.split()[:5]
        short_title = "_".join(words)

    # Sanitize each part
    year = sanitize_filename(year, 10)
    first_author = sanitize_filename(first_author, 30)
    short_title = sanitize_filename(short_title, 60)

    return f"{year}_{first_author}_{short_title}.pdf"


class PDFDownloader:
    """Download PDFs using Unpaywall API.

    Manages downloading PDFs for papers, tracking results,
    and updating database status.
    """

    def __init__(
        self,
        unpaywall: UnpaywallClient,
        paper_repo: PaperRepository,
        output_dir: Path,
    ):
        """Initialize PDF downloader.

        Args:
            unpaywall: Unpaywall API client
            paper_repo: Paper repository for status updates
            output_dir: Directory to save downloaded PDFs
        """
        self.unpaywall = unpaywall
        self.paper_repo = paper_repo
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Statistics
        self._success_count = 0
        self._failed_count = 0
        self._skipped_count = 0

    async def download_paper(self, paper: Paper, retry_failed: bool = False) -> DownloadResult:
        """Download PDF for a single paper.

        Args:
            paper: Paper to download
            retry_failed: Whether to retry if previously failed

        Returns:
            DownloadResult with outcome
        """
        # Check if DOI is available
        if not paper.doi:
            return DownloadResult(
                paper_id=paper.id,
                openalex_id=paper.openalex_id,
                success=False,
                error_message="No DOI available",
            )

        # Check if already downloaded
        if paper.download_status == DownloadStatus.SUCCESS and paper.local_path:
            return DownloadResult(
                paper_id=paper.id,
                openalex_id=paper.openalex_id,
                success=True,
                file_path=paper.local_path,
            )

        # Check if already failed (to avoid re-trying)
        if paper.download_status == DownloadStatus.FAILED and not retry_failed:
            return DownloadResult(
                paper_id=paper.id,
                openalex_id=paper.openalex_id,
                success=False,
                error_message="Previously failed (skipped)",
            )

        # Generate filename
        filename = generate_pdf_filename(paper)
        save_path = self.output_dir / filename

        # Check if file already exists
        if save_path.exists():
            # Update status
            self.paper_repo.update_download_status(
                paper.id, DownloadStatus.SUCCESS, save_path
            )
            self._success_count += 1

            return DownloadResult(
                paper_id=paper.id,
                openalex_id=paper.openalex_id,
                success=True,
                file_path=save_path,
            )

        # Try to download
        try:
            success, oa_info = await self.unpaywall.check_and_download(
                paper.doi, save_path, fallback_to_landing=True
            )

            if success:
                # Update status
                self.paper_repo.update_download_status(
                    paper.id, DownloadStatus.SUCCESS, save_path
                )
                self._success_count += 1

                return DownloadResult(
                    paper_id=paper.id,
                    openalex_id=paper.openalex_id,
                    success=True,
                    file_path=save_path,
                    credits_used=0,  # Unpaywall is free
                    candidate_urls=[oa_info.pdf_url] if oa_info.pdf_url else [],
                    debug_info=oa_info.original_json,
                )
            else:
                # Download failed
                error_msg = "No open access PDF available"
                candidate_urls = []
                if oa_info:
                    if oa_info.pdf_url:
                        candidate_urls.append(oa_info.pdf_url)
                    if oa_info.landing_url:
                        candidate_urls.append(oa_info.landing_url)
                        
                    if not oa_info.is_oa:
                        error_msg = "Not open access"
                    elif not oa_info.pdf_url and not oa_info.landing_url:
                        error_msg = "No PDF URL available"
                    else:
                         # OA is true and we have URLs, but download failed (check_and_download returned False)
                        error_msg = "Download failed (OA Available)"

                self.paper_repo.update_download_status(paper.id, DownloadStatus.FAILED)
                self._failed_count += 1

                return DownloadResult(
                    paper_id=paper.id,
                    openalex_id=paper.openalex_id,
                    success=False,
                    error_message=error_msg,
                    candidate_urls=candidate_urls,
                    debug_info=oa_info.original_json if oa_info else None,
                )

        except Exception as e:
            # Error during download
            self.paper_repo.update_download_status(paper.id, DownloadStatus.FAILED)
            self._failed_count += 1

            return DownloadResult(
                paper_id=paper.id,
                openalex_id=paper.openalex_id,
                success=False,
                error_message=str(e),
                # We can't easily capture oa_info here if exception happened in check_and_download,
                # but if we separate check and download we could.
                # For now, let's leave empty.
            )

    async def download_batch(
        self,
        papers: list[Paper],
        concurrency: int = 3,
        progress_callback=None,
        retry_failed: bool = False,
    ) -> list[DownloadResult]:
        """Download PDFs for multiple papers concurrently.

        Args:
            papers: List of papers to download
            concurrency: Maximum concurrent downloads
            progress_callback: Optional callback for progress updates

        Returns:
            List of DownloadResult objects
        """
        results: list[DownloadResult] = []
        semaphore = asyncio.Semaphore(concurrency)

        # Download all papers
        completed_count = 0

        async def download_with_semaphore(paper: Paper) -> DownloadResult:
            nonlocal completed_count
            async with semaphore:
                try:
                    result = await self.download_paper(paper, retry_failed=retry_failed)
                except Exception as e:
                    # Fallback catch-all for any error during download_paper
                    result = DownloadResult(
                        paper_id=paper.id,
                        openalex_id=paper.openalex_id,
                        success=False,
                        error_message=f"Critical error: {str(e)}"
                    )
                
                completed_count += 1
                if progress_callback:
                    try:
                        # Include error message in status if failed
                        err_detail = ""
                        if not result.success and result.error_message:
                            # Shorten error message
                            clean_err = result.error_message
                            if "No DOI available" in clean_err:
                                clean_err = "No DOI"
                            elif "No open access PDF" in clean_err:
                                clean_err = "Not OA"
                            elif "Not open access" in clean_err:
                                clean_err = "Not OA" 
                            elif "No PDF URL" in clean_err:
                                clean_err = "No PDF URL"
                            
                            err_detail = f" ({clean_err})"

                        await progress_callback(
                            completed_count, len(papers), result, err_detail
                        )
                    except Exception:
                        pass # Ignore callback errors
                return result

        tasks = [download_with_semaphore(paper) for paper in papers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to failed results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                paper = papers[i]
                processed_results.append(
                    DownloadResult(
                        paper_id=paper.id,
                        openalex_id=paper.openalex_id,
                        success=False,
                        error_message=str(result),
                    )
                )
            else:
                processed_results.append(result)

        return processed_results

    def get_statistics(self) -> dict:
        """Get download statistics.

        Returns:
            Dictionary with success, failed, and skipped counts
        """
        return {
            "success": self._success_count,
            "failed": self._failed_count,
            "skipped": self._skipped_count,
            "total": self._success_count + self._failed_count + self._skipped_count,
        }

    def reset_statistics(self) -> None:
        """Reset download statistics."""
        self._success_count = 0
        self._failed_count = 0
        self._skipped_count = 0