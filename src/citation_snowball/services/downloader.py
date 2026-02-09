"""PDF download service backed by pdf_downloader package."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from citation_snowball.core.models import DownloadResult, DownloadStatus, Paper
from citation_snowball.db.repository import PaperRepository


class PDFDownloader:
    """Download PDFs for papers via pdf_downloader batch API."""

    def __init__(
        self,
        paper_repo: PaperRepository,
        output_dir: Path,
        api_key: str,
    ):
        self.paper_repo = paper_repo
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key
        self._success_count = 0
        self._failed_count = 0
        self._skipped_count = 0

        repo_root = Path(__file__).resolve().parents[3]
        pdf_downloader_src = repo_root / "pdf_downloader" / "src"
        if pdf_downloader_src.exists():
            sys.path.insert(0, str(pdf_downloader_src))
        from pdf_downloader.api import download_openalex_ids

        self._download_openalex_ids = download_openalex_ids

    async def download_batch(
        self,
        papers: list[Paper],
        concurrency: int = 3,
        progress_callback=None,
        retry_failed: bool = False,
    ) -> list[DownloadResult]:
        """Download a paper batch and return DownloadResult entries."""
        candidates = [p for p in papers if not p.local_path]
        openalex_ids = {p.openalex_id for p in candidates}

        batch_result = await asyncio.to_thread(
            self._download_openalex_ids,
            openalex_ids,
            output_dir=self.output_dir,
            skip_existing=True,
            delay=0.0,
            api_key=self.api_key,
        )

        failures_by_id = {f.openalex_id: f for f in batch_result.failures}
        paper_by_id = {p.openalex_id: p for p in candidates}

        results: list[DownloadResult] = []
        completed = 0
        total = len(candidates)

        for openalex_id, paper in paper_by_id.items():
            fail = failures_by_id.get(openalex_id)
            if fail:
                self.paper_repo.update_download_status(paper.id, DownloadStatus.FAILED)
                result = DownloadResult(
                    paper_id=paper.id,
                    openalex_id=openalex_id,
                    success=False,
                    error_message=fail.reason,
                    candidate_urls=fail.candidate_urls
                    + ([fail.landing_page_url] if fail.landing_page_url else []),
                    debug_info={"openalex_id": fail.openalex_id, "oa_status": fail.oa_status},
                )
                self._failed_count += 1
            else:
                file_path = None
                if openalex_id in batch_result.downloaded_paths:
                    file_path = Path(batch_result.downloaded_paths[openalex_id])
                self.paper_repo.update_download_status(
                    paper.id, DownloadStatus.SUCCESS, file_path
                )
                result = DownloadResult(
                    paper_id=paper.id,
                    openalex_id=openalex_id,
                    success=True,
                    file_path=file_path,
                )
                self._success_count += 1
                if file_path and file_path.exists():
                    pass

            results.append(result)
            completed += 1
            if progress_callback:
                err_detail = f" ({result.error_message})" if (not result.success and result.error_message) else ""
                await progress_callback(completed, total, result, err_detail)

        # Estimate skipped as successes with pre-existing files recorded by API
        self._skipped_count += batch_result.skipped

        return results

    def get_statistics(self) -> dict:
        return {
            "success": self._success_count,
            "failed": self._failed_count,
            "skipped": self._skipped_count,
            "total": self._success_count + self._failed_count + self._skipped_count,
        }

    def reset_statistics(self) -> None:
        self._success_count = 0
        self._failed_count = 0
        self._skipped_count = 0

