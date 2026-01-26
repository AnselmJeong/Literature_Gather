"""OpenAlex API client with rate limiting and caching."""
import asyncio
import hashlib
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from citation_snowball.config import get_settings
from citation_snowball.core.models import Work, WorksResponse
from citation_snowball.db.database import Database
from citation_snowball.db.repository import CacheRepository


class OpenAlexClient:
    """Client for OpenAlex API with rate limiting and caching."""

    OPENALEX_BASE = "https://api.openalex.org"
    DEFAULT_PER_PAGE = 50
    MAX_BATCH_SIZE = 50

    def __init__(
        self,
        email: str | None = None,
        cache_ttl_days: int = 7,
        rate_limit: int = 10,
        db: Database | None = None,
    ):
        """Initialize OpenAlex client.

        Args:
            email: Email address for polite pool access
            cache_ttl_days: Cache duration in days
            rate_limit: Max requests per second
            db: Database for caching (optional, uses in-memory if None)
        """
        self.settings = get_settings()
        self.email = email or self.settings.openalex_api_key
        self.cache_ttl_days = cache_ttl_days
        self.rate_limit = rate_limit

        # Async HTTP client
        self._client = httpx.AsyncClient(timeout=60.0)
        self._rate_limiter = asyncio.Semaphore(rate_limit)

        # Cache
        if db:
            self._cache = CacheRepository(db)
        else:
            self._cache = None

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

    def _cache_key(self, endpoint: str, params: dict[str, Any]) -> str:
        """Generate cache key for request."""
        key_data = f"{endpoint}:{sorted(params.items())}"
        return hashlib.md5(key_data.encode()).hexdigest()

    async def _get_cached(self, key: str) -> dict[str, Any] | None:
        """Get cached response if available."""
        if not self._cache:
            return None
        return self._cache.get(key)

    async def _set_cached(self, key: str, response: dict[str, Any]) -> None:
        """Cache a response."""
        if not self._cache:
            return
        self._cache.set(key, response, self.cache_ttl_days)

    async def _wait_rate_limit(self) -> None:
        """Wait to respect rate limit."""
        now = asyncio.get_event_loop().time()
        time_since_last = now - self._last_request_time
        if time_since_last < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - time_since_last)
        self._last_request_time = asyncio.get_event_loop().time()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
    async def _fetch(self, url: str, use_cache: bool = True) -> dict[str, Any]:
        """Fetch data from OpenAlex API with retry."""
        # Check cache
        if use_cache and self._cache:
            cache_key = self._cache_key(url, {})
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        # Respect rate limit
        await self._wait_rate_limit()

        async with self._rate_limiter:
            response = await self._client.get(url)

        if response.status_code == 429:
            raise httpx.HTTPStatusError(
                "Rate limited", request=response.request, response=response
            )
        response.raise_for_status()
        data = response.json()

        # Cache response
        if use_cache and self._cache:
            await self._set_cached(cache_key, data)

        return data

    def _build_url(self, endpoint: str, params: dict[str, Any]) -> str:
        """Build URL with parameters."""
        # Add email for polite pool
        if self.email:
            params["mailto"] = self.email

        query_parts = [f"{k}={v}" for k, v in params.items() if v is not None]
        query = "&".join(query_parts)
        return f"{self.OPENALEX_BASE}{endpoint}?{query}"

    async def get_work(self, work_id: str) -> Work:
        """Get a single work by OpenAlex ID.

        Args:
            work_id: OpenAlex work ID (e.g., "W2741809807" or "https://openalex.org/W2741809807")

        Returns:
            Work object

        Raises:
            httpx.HTTPError: If request fails
            ValueError: If work_id is invalid
        """
        # Clean up ID format
        clean_id = work_id.replace("https://openalex.org/", "")

        url = self._build_url(f"/works/{clean_id}", {})
        data = await self._fetch(url)

        return Work(**data)

    async def get_citing_works(
        self,
        work_id: str,
        per_page: int | None = None,
        cursor: str | None = None,
    ) -> WorksResponse:
        """Get works that cite the specified work (forward citations).

        Args:
            work_id: OpenAlex work ID
            per_page: Results per page (default: DEFAULT_PER_PAGE)
            cursor: Pagination cursor

        Returns:
            WorksResponse with paginated results
        """
        # Clean up ID format
        clean_id = work_id.replace("https://openalex.org/", "")

        params: dict[str, Any] = {
            "filter": f"cites:{clean_id}",
            "per_page": per_page or self.DEFAULT_PER_PAGE,
        }
        if cursor:
            params["cursor"] = cursor

        url = self._build_url("/works", params)
        data = await self._fetch(url)

        return WorksResponse(**data)

    async def get_author_works(
        self,
        author_id: str,
        from_year: int | None = None,
        per_page: int | None = None,
    ) -> WorksResponse:
        """Get works by a specific author.

        Args:
            author_id: OpenAlex author ID (e.g., "A5022568412")
            from_year: Filter works from this year onwards
            per_page: Results per page (default: DEFAULT_PER_PAGE)

        Returns:
            WorksResponse with paginated results
        """
        # Clean up ID format
        clean_id = author_id.replace("https://openalex.org/", "")

        params: dict[str, Any] = {
            "filter": f"author.id:{clean_id}",
            "per_page": per_page or self.DEFAULT_PER_PAGE,
            "sort": "publication_date:desc",
        }
        if from_year:
            params["filter"] += f",from_publication_date:{from_year}-01-01"

        url = self._build_url("/works", params)
        data = await self._fetch(url)

        return WorksResponse(**data)

    async def search_by_doi(self, doi: str) -> Work | None:
        """Search for a work by DOI.

        Args:
            doi: DOI string (e.g., "10.1038/s41586-019-1724-z" or full URL)

        Returns:
            Work object if found, None otherwise
        """
        try:
            # Ensure DOI has https://doi.org/ prefix for OpenAlex ID lookup
            if not doi.startswith("http"):
                doi_id = f"https://doi.org/{doi}"
            else:
                # Normalize http -> https
                doi_id = doi.replace("http://", "https://")

            # Use the full DOI URL as the ID
            url = self._build_url(f"/works/{doi_id}", {})
            data = await self._fetch(url)
            return Work(**data)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def search_by_title(self, title: str, per_page: int = 5) -> WorksResponse:
        """Search for works by title (fuzzy search).

        Args:
            title: Paper title
            per_page: Number of results to return (default: 5)

        Returns:
            WorksResponse with matching works
        """
        params: dict[str, Any] = {
            "search": title,
            "per_page": per_page,
        }

        url = self._build_url("/works", params)
        data = await self._fetch(url)

        return WorksResponse(**data)

    async def get_works_batch(self, work_ids: list[str]) -> list[Work]:
        """Get multiple works in batches.

        OpenAlex supports filtering by multiple OpenAlex IDs using pipe separator.

        Args:
            work_ids: List of OpenAlex work IDs

        Returns:
            List of Work objects
        """
        if not work_ids:
            return []

        # Clean up IDs and batch them
        clean_ids = [id.replace("https://openalex.org/", "") for id in work_ids]
        results: list[Work] = []

        # Process in batches
        for i in range(0, len(clean_ids), self.MAX_BATCH_SIZE):
            batch = clean_ids[i : i + self.MAX_BATCH_SIZE]
            filter_str = "|".join(batch)

            params: dict[str, Any] = {
                "filter": f"openalex_id:{filter_str}",
                "per_page": len(batch),
            }

            url = self._build_url("/works", params)
            data = await self._fetch(url)

            works = [Work(**w) for w in data.get("results", [])]
            results.extend(works)

        return results

    async def get_all_citing_works(
        self, work_id: str, max_results: int | None = None
    ) -> list[Work]:
        """Get all citing works with pagination.

        Args:
            work_id: OpenAlex work ID
            max_results: Maximum number of results to return (None for all)

        Returns:
            List of all citing works
        """
        all_works: list[Work] = []
        cursor = "*"

        while True:
            response = await self.get_citing_works(work_id, cursor=cursor)
            all_works.extend(response.results)

            # Check if we have enough results or reached end
            if max_results and len(all_works) >= max_results:
                return all_works[:max_results]

            if not response.next_cursor:
                break

            cursor = response.next_cursor

        return all_works