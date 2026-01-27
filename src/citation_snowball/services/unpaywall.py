"""Unpaywall API client for finding open access PDFs."""
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class OAInfo:
    """Open access information from Unpaywall."""

    is_oa: bool
    pdf_url: str | None
    landing_url: str | None
    version: str | None  # publishedVersion, acceptedVersion, submittedVersion
    version: str | None  # publishedVersion, acceptedVersion, submittedVersion
    host_type: str | None  # publisher, repository
    original_json: dict[str, Any] | None = None  # Full API response


class UnpaywallClient:
    """Client for Unpaywall API to find open access PDFs."""

    UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
    DEFAULT_RATE_LIMIT = 10

    def __init__(self, email: str, rate_limit: int = DEFAULT_RATE_LIMIT):
        """Initialize Unpaywall client.

        Args:
            email: Email address for polite pool access (required)
            rate_limit: Max requests per second (default: 10)
        """
        if not email:
            raise ValueError("Email address is required for Unpaywall API")

        self.email = email
        self.rate_limit = rate_limit
        self._client = httpx.AsyncClient(timeout=30.0)
        self._rate_limiter = asyncio.Semaphore(rate_limit)

        # Request tracking for rate limiting
        self._last_request_time = 0.0
        self._min_request_interval = 1.0 / rate_limit

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _wait_rate_limit(self) -> None:
        """Wait to respect rate limit."""
        now = asyncio.get_event_loop().time()
        time_since_last = now - self._last_request_time
        if time_since_last < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - time_since_last)
        self._last_request_time = asyncio.get_event_loop().time()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
    async def check_oa(self, doi: str) -> OAInfo | None:
        """Check if a DOI has open access availability.

        Args:
            doi: DOI string (e.g., "10.1038/nature12373")

        Returns:
            OAInfo with open access details, or None if DOI not found

        Raises:
            httpx.HTTPError: If request fails
            ValueError: If DOI is invalid
        """
        if not doi:
            raise ValueError("DOI cannot be empty")

        # Clean up DOI format
        clean_doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")

        url = f"{self.UNPAYWALL_BASE}/{clean_doi}?email={self.email}"

        # Respect rate limit
        await self._wait_rate_limit()

        try:
            async with self._rate_limiter:
                response = await self._client.get(url)
            
            if response.status_code == 404:
                return None
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # If rate limited or server error, we might want to just fail this one
            # to let the batch continue
            return None
        except Exception:
            return None

        data = response.json()

        # Get best OA location (might be empty if not OA)
        best_loc = data.get("best_oa_location") or {}

        return OAInfo(
            is_oa=data.get("is_oa", False),
            pdf_url=best_loc.get("url_for_pdf"),
            landing_url=best_loc.get("url"),
            version=best_loc.get("version"),
            host_type=best_loc.get("host_type"),
            original_json=data,
        )

    async def download_pdf(
        self,
        pdf_url: str,
        save_path: Path,
        user_agent: str | None = None,
    ) -> bool:
        """Download a PDF from a URL.

        Args:
            pdf_url: URL to download PDF from
            save_path: Path to save the PDF
            user_agent: Custom User-Agent header

        Returns:
            True if download successful, False otherwise
        """
        try:
            # Use a fresh client for downloading to act like a browser
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as download_client:
                headers = {}
                if user_agent:
                    headers["User-Agent"] = user_agent
                else:
                    # Generic browser user agent to avoid blocking
                    headers["User-Agent"] = (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )

                async with download_client.stream("GET", pdf_url, headers=headers) as response:
                    response.raise_for_status()

                    # Verify it's a PDF - check Content-Type first
                    content_type = response.headers.get("content-type", "").lower()
                    
                    # Store iterator to avoid consuming it twice
                    chunk_iterator = response.aiter_bytes(chunk_size=8192)
                    
                    # Read first chunk for magic bytes check
                    first_chunk = b""
                    async for chunk in chunk_iterator:
                        first_chunk = chunk
                        break
                    
                    if not first_chunk:
                        return False

                    is_pdf = False
                    if "application/pdf" in content_type or "application/x-pdf" in content_type:
                        is_pdf = True
                    elif first_chunk.startswith(b"%PDF-"):
                        is_pdf = True
                    elif "pdf" in content_type:  # Lenient check
                        is_pdf = True
                    
                    if not is_pdf:
                        return False

                    # Ensure parent directory exists
                    save_path.parent.mkdir(parents=True, exist_ok=True)

                    # Write to file - use the SAME iterator to get remaining chunks
                    with open(save_path, "wb") as f:
                        f.write(first_chunk)
                        async for chunk in chunk_iterator:  # Continue from same iterator
                            f.write(chunk)
                    
                    # Validate file size - a real PDF should be at least a few KB
                    file_size = save_path.stat().st_size
                    if file_size < 5000:  # Less than 5KB is suspicious
                        save_path.unlink()  # Delete invalid file
                        return False
                    
                    return True

        except (httpx.HTTPError, IOError, Exception):
            # Clean up partial file if it exists
            if save_path.exists():
                try:
                    save_path.unlink()
                except:
                    pass
            return False

    async def check_and_download(
        self,
        doi: str,
        save_path: Path,
        fallback_to_landing: bool = False,
    ) -> tuple[bool, OAInfo | None]:
        """Check OA availability and download PDF in one call.

        Args:
            doi: DOI string
            save_path: Path to save the PDF
            fallback_to_landing: If PDF unavailable, try landing page

        Returns:
            Tuple of (success: bool, oa_info: OAInfo | None)
        """
        oa_info = await self.check_oa(doi)

        if not oa_info or not oa_info.is_oa:
            return False, oa_info

        # Try PDF URL first
        if oa_info.pdf_url:
            success = await self.download_pdf(oa_info.pdf_url, save_path)
            if success:
                return True, oa_info

        # Fallback to landing page if enabled and available
        if fallback_to_landing and oa_info.landing_url:
            success = await self.download_pdf(oa_info.landing_url, save_path)
            if success:
                return True, oa_info

        return False, oa_info