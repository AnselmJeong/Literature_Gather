"""Semantic Scholar API client with rate limiting and caching."""
import asyncio
import hashlib
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from citation_snowball.config import get_settings
from citation_snowball.db.database import Database
from citation_snowball.config import get_settings
from citation_snowball.core.models import Work, WorksResponse
from citation_snowball.db.database import Database
from citation_snowball.db.repository import CacheRepository


class SemanticScholarClient:
    """Client for Semantic Scholar API with rate limiting and caching.
    
    API Documentation: https://api.semanticscholar.org/api-docs/graph
    """

    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    DEFAULT_LIMIT = 100
    MAX_BATCH_SIZE = 500

    # Default fields to request for papers
    PAPER_FIELDS = (
        "paperId,corpusId,externalIds,url,title,abstract,venue,publicationVenue,"
        "year,referenceCount,citationCount,influentialCitationCount,isOpenAccess,"
        "openAccessPdf,fieldsOfStudy,s2FieldsOfStudy,publicationTypes,publicationDate,"
        "journal,citationStyles,authors"
    )
    
    # Fields for citations/references (includes paper details)
    CITATION_FIELDS = (
        "contexts,intents,isInfluential,paperId,corpusId,externalIds,url,title,"
        "abstract,venue,year,referenceCount,citationCount,influentialCitationCount,"
        "isOpenAccess,openAccessPdf,fieldsOfStudy,publicationTypes,publicationDate,authors"
    )
    
    # Fields for author papers
    AUTHOR_PAPER_FIELDS = (
        "paperId,corpusId,externalIds,title,venue,year,referenceCount,"
        "citationCount,influentialCitationCount,isOpenAccess,authors"
    )

    def __init__(
        self,
        api_key: str | None = None,
        cache_ttl_days: int = 7,
        rate_limit: int = 100,
        db: Database | None = None,
    ):
        """Initialize Semantic Scholar client.

        Args:
            api_key: Semantic Scholar API key
            cache_ttl_days: Cache duration in days
            rate_limit: Max requests per second
            db: Database for caching (optional, uses in-memory if None)
        """
        self.settings = get_settings()
        self.api_key = api_key or self.settings.semantic_scholar_api_key
        self.cache_ttl_days = cache_ttl_days
        self.rate_limit = rate_limit

        # HTTP client with API key header
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        
        self._client = httpx.AsyncClient(
            timeout=60.0,
            headers=headers,
        )
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

    def _cache_key(self, url: str) -> str:
        """Generate cache key for request."""
        return hashlib.md5(url.encode()).hexdigest()

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
    async def _fetch(
        self, 
        url: str, 
        use_cache: bool = True,
        method: str = "GET",
        json_body: dict | None = None,
    ) -> dict[str, Any]:
        """Fetch data from Semantic Scholar API with retry.
        
        Args:
            url: Full URL to fetch
            use_cache: Whether to use caching
            method: HTTP method (GET or POST)
            json_body: JSON body for POST requests
            
        Returns:
            JSON response as dict
        """
        # Check cache (only for GET requests)
        if use_cache and method == "GET" and self._cache:
            cache_key = self._cache_key(url)
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        # Respect rate limit
        await self._wait_rate_limit()

        async with self._rate_limiter:
            if method == "POST":
                response = await self._client.post(url, json=json_body)
            else:
                response = await self._client.get(url)

        if response.status_code == 429:
            raise httpx.HTTPStatusError(
                "Rate limited", request=response.request, response=response
            )
        if response.status_code == 404:
            raise httpx.HTTPStatusError(
                "Not found", request=response.request, response=response
            )
        response.raise_for_status()
        data = response.json()

        # Cache response (only for GET requests)
        if use_cache and method == "GET" and self._cache:
            await self._set_cached(cache_key, data)

        return data

    def _build_url(self, endpoint: str, params: dict[str, Any] | None = None) -> str:
        """Build URL with query parameters."""
        url = f"{self.BASE_URL}{endpoint}"
        if params:
            query_parts = [f"{k}={v}" for k, v in params.items() if v is not None]
            if query_parts:
                url = f"{url}?{'&'.join(query_parts)}"
        return url

    # ========================================================================
    # Paper Endpoints
    # ========================================================================

    async def get_paper(
        self, 
        paper_id: str, 
        fields: str | None = None,
    ) -> Work:
        """Get a single paper by ID.
        
        Supports various ID formats:
        - Semantic Scholar ID: "649def34f8be52c8b66281af98ae884c09aef38b"
        - DOI: "DOI:10.1038/s41586-019-1724-z" 
        - PMID: "PMID:19872477"
        - ArXiv: "ARXIV:2106.15928"
        - CorpusId: "CorpusId:215416146"

        Args:
            paper_id: Paper identifier (various formats supported)
            fields: Comma-separated list of fields to return

        Returns:
            Paper data as dict

        Raises:
            httpx.HTTPError: If request fails
        """
        params = {"fields": fields or self.PAPER_FIELDS}
        url = self._build_url(f"/paper/{paper_id}", params)
        data = await self._fetch(url)
        return Work(**data)

    async def get_paper_citations(
        self,
        paper_id: str,
        fields: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> WorksResponse:
        """Get papers that cite this paper (forward citations).

        Args:
            paper_id: Paper identifier
            fields: Fields to return for citing papers
            limit: Maximum number of results (default: 100, max: 1000)
            offset: Starting position for pagination

        Returns:
            Paginated response with citation data
        """
        params = {
            "fields": fields or self.CITATION_FIELDS,
            "limit": limit or self.DEFAULT_LIMIT,
            "offset": offset,
        }
        url = self._build_url(f"/paper/{paper_id}/citations", params)
        data = await self._fetch(url)
        # S2 citations endpoint returns slightly different structure, need to map citingPaper to Work
        if "data" in data:
            papers = []
            for item in data["data"]:
                if "citingPaper" in item:
                    # Flatten citingPaper into the main Work object
                    paper_data = item["citingPaper"]
                    # Copy context/intents/isInfluential if needed
                    # For now just extract the paper
                    papers.append(Work(**paper_data))
            data["data"] = papers
        return WorksResponse(**data)

    async def get_paper_references(
        self,
        paper_id: str,
        fields: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> WorksResponse:
        """Get papers cited by this paper (backward citations/references).

        Args:
            paper_id: Paper identifier
            fields: Fields to return for referenced papers
            limit: Maximum number of results (default: 100, max: 1000)
            offset: Starting position for pagination

        Returns:
            Paginated response with reference data
        """
        params = {
            "fields": fields or self.CITATION_FIELDS,
            "limit": limit or self.DEFAULT_LIMIT,
            "offset": offset,
        }
        url = self._build_url(f"/paper/{paper_id}/references", params)
        data = await self._fetch(url)
        # S2 references endpoint returns similar structure to citations
        if "data" in data:
            papers = []
            for item in data["data"]:
                if "citedPaper" in item:
                    paper_data = item["citedPaper"]
                    papers.append(Work(**paper_data))
            data["data"] = papers
        return WorksResponse(**data)

    async def search_papers(
        self,
        query: str,
        fields: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        year: str | None = None,
        fields_of_study: str | None = None,
    ) -> WorksResponse:
        """Search for papers by keyword query.

        Args:
            query: Search query string
            fields: Fields to return
            limit: Maximum results (default: 100, max: 100)
            offset: Starting position
            year: Filter by year or range (e.g., "2019", "2016-2020", "2010-")
            fields_of_study: Filter by field (e.g., "Computer Science,Medicine")

        Returns:
            Search results with total, offset, next, and data array
        """
        params = {
            "query": query,
            "fields": fields or self.PAPER_FIELDS,
            "limit": min(limit or self.DEFAULT_LIMIT, 100),  # Max 100 for search
            "offset": offset,
        }
        if year:
            params["year"] = year
        if fields_of_study:
            params["fieldsOfStudy"] = fields_of_study
            
        url = self._build_url("/paper/search", params)
        data = await self._fetch(url)
        return WorksResponse(**data)

    async def search_paper_by_title(
        self,
        title: str,
        fields: str | None = None,
    ) -> Work | None:
        """Search for a paper by exact title match.

        Args:
            title: Paper title to match
            fields: Fields to return

        Returns:
            Best matching paper or None if not found
        """
        params = {
            "query": title,
            "fields": fields or self.PAPER_FIELDS,
        }
        url = self._build_url("/paper/search/match", params)
        try:
            result = await self._fetch(url)
            if result.get("data"):
                return Work(**result["data"][0])
            return None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def get_papers_batch(
        self,
        paper_ids: list[str],
        fields: str | None = None,
    ) -> list[Work]:
        """Get multiple papers in a single batch request.

        Args:
            paper_ids: List of paper IDs (max 500)
            fields: Fields to return

        Returns:
            List of paper data dicts
        """
        if not paper_ids:
            return []

        results = []
        
        # Process in batches of MAX_BATCH_SIZE
        for i in range(0, len(paper_ids), self.MAX_BATCH_SIZE):
            batch = paper_ids[i : i + self.MAX_BATCH_SIZE]
            
            params = {"fields": fields or self.PAPER_FIELDS}
            url = self._build_url("/paper/batch", params)
            
            data = await self._fetch(
                url, 
                method="POST", 
                json_body={"ids": batch},
                use_cache=False,  # Don't cache batch requests
            )
            
            # Batch returns a list directly
            if isinstance(data, list):
                results.extend([Work(**p) for p in data if p is not None])
            
        return results

    # ========================================================================
    # Author Endpoints
    # ========================================================================

    async def get_author_papers(
        self,
        author_id: str,
        fields: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        year: str | None = None,
    ) -> WorksResponse:
        """Get papers by a specific author.

        Args:
            author_id: Semantic Scholar author ID
            fields: Fields to return for papers
            limit: Maximum results (default: 100, max: 1000)
            offset: Starting position
            year: Filter by publication year range

        Returns:
            Paginated response with author's papers
        """
        params = {
            "fields": fields or self.AUTHOR_PAPER_FIELDS,
            "limit": limit or self.DEFAULT_LIMIT,
            "offset": offset,
        }
        if year:
            params["publicationDateOrYear"] = year
            
        url = self._build_url(f"/author/{author_id}/papers", params)
        data = await self._fetch(url)
        return WorksResponse(**data)

    async def get_author(
        self,
        author_id: str,
        fields: str = "authorId,name,affiliations,homepage,paperCount,citationCount,hIndex",
    ) -> dict[str, Any]:
        """Get author details.

        Args:
            author_id: Semantic Scholar author ID
            fields: Fields to return

        Returns:
            Author data dict
        """
        params = {"fields": fields}
        url = self._build_url(f"/author/{author_id}", params)
        return await self._fetch(url)

    # ========================================================================
    # Helper Methods
    # ========================================================================

    async def get_all_citations(
        self, 
        paper_id: str, 
        max_results: int | None = None,
    ) -> list[Work]:
        """Get all papers citing this paper with pagination.

        Args:
            paper_id: Paper identifier
            max_results: Maximum number of results (None for all)

        Returns:
            List of all citing paper data
        """
        all_results = []
        offset = 0
        limit = 1000  # Max per request

        while True:
            response = await self.get_paper_citations(
                paper_id, limit=limit, offset=offset
            )
            
            data = response.results
            if not data:
                break
                
            all_results.extend(data)
            
            # Check if we have enough or reached the end
            if max_results and len(all_results) >= max_results:
                return all_results[:max_results]
            
            # Check for next page
            if not response.next:
                break
                
            offset = response.next

        return all_results

    async def get_all_references(
        self, 
        paper_id: str, 
        max_results: int | None = None,
    ) -> list[Work]:
        """Get all papers referenced by this paper with pagination.

        Args:
            paper_id: Paper identifier
            max_results: Maximum number of results (None for all)

        Returns:
            List of all referenced paper data
        """
        all_results = []
        offset = 0
        limit = 1000  # Max per request

        while True:
            response = await self.get_paper_references(
                paper_id, limit=limit, offset=offset
            )
            
            data = response.results
            if not data:
                break
                
            all_results.extend(data)
            
            # Check if we have enough or reached the end
            if max_results and len(all_results) >= max_results:
                return all_results[:max_results]
            
            # Check for next page
            if not response.next:
                break
                
            offset = response.next

        return all_results

    async def search_by_doi(self, doi: str) -> Work | None:
        """Search for a paper by DOI.

        Args:
            doi: DOI string (with or without prefix/URL)

        Returns:
            Paper data or None if not found
        """
        # Clean DOI format
        clean_doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        
        try:
            return await self.get_paper(f"DOI:{clean_doi}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
