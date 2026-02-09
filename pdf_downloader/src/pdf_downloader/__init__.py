"""pdf_downloader package."""

from pdf_downloader.api import BatchDownloadResult, DownloadFailure, download_openalex_ids

__all__ = ["download_openalex_ids", "BatchDownloadResult", "DownloadFailure"]
