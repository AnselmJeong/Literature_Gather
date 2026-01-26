"""Crossref API client for fallback DOI lookup by title."""
import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from citation_snowball.core.models import AuthorInfo, Work


@dataclass
class CrossrefWork:
    """Minimal work representation from Crossref."""

    title: str
    doi: str | None
    year: str | None
    authors: list[AuthorInfo]


class CrossrefClient:
    """Client for Crossref API - fallback for DOI lookup by title."""

    CROSSREF_BASE = "https://api.crossref.org/works"
    DEFAULT_RATE_LIMIT = 50

    def __init__(self, email: str | None = None, rate_limit: int = DEFAULT_RATE_LIMIT):
        """Initialize Crossref client.

        Args:
            email: Email address for polite pool access (optional)
            rate_limit: Max requests per second (default: 50)
        """
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

    def _build_url(self, params: dict[str, Any]) -> str:
        """Build URL with parameters."""
        query_parts = []
        for k, v in params.items():
            if v is not None:
                query_parts.append(f"{k}={v}")

        query = "&".join(query_parts)
        return f"{self.CROSSREF_BASE}?{query}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
    async def search_by_title(
        self, title: str, max_results: int = 5
    ) -> list[CrossrefWork]:
        """Search for works by title.

        Args:
            title: Paper title to search for
            max_results: Maximum number of results to return

        Returns:
            List of CrossrefWork objects matching the title
        """
        if not title:
            return []

        # URL encode the title for the query parameter
        from urllib.parse import quote

        params = {
            "query.title": quote(title),
            "rows": max_results,
            "select": "title,DOI,author,issued,published-print",
        }

        if self.email:
            params["mailto"] = self.email

        url = self._build_url(params)

        # Respect rate limit
        await self._wait_rate_limit()

        async with self._rate_limiter:
            response = await self._client.get(url)

        response.raise_for_status()
        data = response.json()

        results: list[CrossrefWork] = []

        for item in data.get("message", {}).get("items", []):
            # Extract title
            titles = item.get("title", [])
            work_title = titles[0] if titles else ""

            # Extract DOI
            doi = item.get("DOI")

            # Extract year
            year = None
            issued = item.get("issued", {})
            date_parts = issued.get("date-parts", [[]])
            if date_parts and date_parts[0]:
                year = str(date_parts[0][0])

            # Extract authors
            authors: list[AuthorInfo] = []
            for author_data in item.get("author", []):
                given = author_data.get("given", "")
                family = author_data.get("family", "")
                name = f"{given} {family}".strip()

                if name:
                    authors.append(
                        AuthorInfo(
                            id="",  # Crossref doesn't provide OpenAlex IDs
                            display_name=name,
                            orcid=author_data.get("ORCID"),
                        )
                    )

            results.append(
                CrossrefWork(
                    title=work_title,
                    doi=doi,
                    year=year,
                    authors=authors,
                )
            )

        return results

    async def get_doi_by_title(self, title: str) -> str | None:
        """Get DOI for a title (best match).

        Args:
            title: Paper title

        Returns:
            DOI string if found, None otherwise
        """
        results = await self.search_by_title(title, max_results=1)

        if results:
            return results[0].doi

        return None

    async def crossref_to_work(self, crossref_work: CrossrefWork) -> Work:
        """Convert a CrossrefWork to a Work model.

        Note: This creates a minimal Work object. For full metadata,
        use the OpenAlex API with the DOI.

        Args:
            crossref_work: Crossref work object

        Returns:
            Work object with basic metadata
        """
        return Work(
            id="",  # Will be filled by OpenAlex lookup
            doi=crossref_work.doi,
            title=crossref_work.title,
            publication_year=int(crossref_work.year) if crossref_work.year else None,
            authorships=[
                {
                    "author": a.model_dump(),
                }
                for a in crossref_work.authors
            ],
        )