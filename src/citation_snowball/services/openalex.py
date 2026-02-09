"""OpenAlex API client with rate limiting and caching."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any
from urllib.parse import quote

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from citation_snowball.config import get_settings
from citation_snowball.core.models import OpenAccessPdf, S2Author, Work, WorksResponse
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
        rate_limit: int | None = None,
        db: Database | None = None,
    ):
        self.settings = get_settings()
        self.identity = email or self.settings.openalex_api_key
        self.cache_ttl_days = cache_ttl_days
        self.rate_limit = rate_limit or self.settings.openalex_rate_limit

        self._client = httpx.AsyncClient(timeout=60.0)
        self._rate_limiter = asyncio.Semaphore(self.rate_limit)

        self._cache = CacheRepository(db) if db else None

        self._last_request_time = 0.0
        self._min_request_interval = 1.0 / self.rate_limit

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _cache_key(self, endpoint: str, params: dict[str, Any]) -> str:
        key_data = f"{endpoint}:{sorted(params.items())}"
        return hashlib.md5(key_data.encode()).hexdigest()

    async def _get_cached(self, key: str) -> dict[str, Any] | None:
        if not self._cache:
            return None
        return self._cache.get(key)

    async def _set_cached(self, key: str, response: dict[str, Any]) -> None:
        if not self._cache:
            return
        self._cache.set(key, response, self.cache_ttl_days)

    async def _wait_rate_limit(self) -> None:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
    async def _fetch(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        cache_key = self._cache_key(endpoint, params)
        if self._cache:
            cached = await self._get_cached(cache_key)
            if cached:
                return cached

        url = self._build_url(endpoint, params)
        await self._wait_rate_limit()
        async with self._rate_limiter:
            response = await self._client.get(url)

        if response.status_code == 429:
            raise httpx.HTTPStatusError(
                "Rate limited", request=response.request, response=response
            )
        response.raise_for_status()
        payload = response.json()

        if self._cache:
            await self._set_cached(cache_key, payload)

        return payload

    def _build_url(self, endpoint: str, params: dict[str, Any]) -> str:
        merged = dict(params)
        if self.identity:
            if "@" in self.identity:
                merged["mailto"] = self.identity
            else:
                merged["api_key"] = self.identity

        query = "&".join(f"{k}={v}" for k, v in merged.items() if v is not None)
        return f"{self.OPENALEX_BASE}{endpoint}?{query}" if query else f"{self.OPENALEX_BASE}{endpoint}"

    @staticmethod
    def _clean_openalex_id(value: str | None) -> str | None:
        if not value:
            return None
        return value.replace("https://openalex.org/", "")

    @staticmethod
    def _clean_doi(value: str | None) -> str | None:
        if not value:
            return None
        return value.replace("https://doi.org/", "").replace("http://doi.org/", "")

    def _normalize_work(self, raw: dict[str, Any]) -> Work:
        work_id_url = raw.get("id")
        work_id = self._clean_openalex_id(work_id_url) or ""

        authors: list[S2Author] = []
        for authorship in raw.get("authorships", []) or []:
            author = authorship.get("author", {}) or {}
            authors.append(
                S2Author(
                    authorId=self._clean_openalex_id(author.get("id")),
                    name=author.get("display_name"),
                )
            )

        ids = raw.get("ids", {}) or {}
        doi = raw.get("doi") or ids.get("doi")
        pmid = ids.get("pmid")
        external_ids: dict[str, str] = {}
        if doi:
            external_ids["DOI"] = self._clean_doi(doi) or doi
        if pmid:
            external_ids["PubMed"] = str(pmid).split("/")[-1]

        best_oa = raw.get("best_oa_location") or {}
        primary_location = raw.get("primary_location") or {}
        open_access = raw.get("open_access") or {}
        pdf_url = best_oa.get("pdf_url") or primary_location.get("pdf_url")
        source = primary_location.get("source") or {}
        venue = source.get("display_name")

        return Work(
            paperId=work_id,
            externalIds=external_ids or None,
            url=work_id_url,
            title=raw.get("title"),
            abstract=raw.get("abstract"),
            venue=venue,
            year=raw.get("publication_year"),
            publicationDate=raw.get("publication_date"),
            publicationTypes=[raw.get("type")] if raw.get("type") else None,
            referenceCount=len(raw.get("referenced_works") or []),
            citationCount=raw.get("cited_by_count") or 0,
            influentialCitationCount=0,
            isOpenAccess=bool(open_access.get("is_oa", raw.get("is_oa", False))),
            openAccessPdf=OpenAccessPdf(url=pdf_url) if pdf_url else None,
            authors=authors,
            journal={"name": venue} if venue else None,
            referenced_works=[self._clean_openalex_id(x) or x for x in (raw.get("referenced_works") or [])],
            counts_by_year=raw.get("counts_by_year") or [],
            type=raw.get("type"),
            language=raw.get("language"),
            is_retracted=bool(raw.get("is_retracted", False)),
        )

    def _to_works_response(self, payload: dict[str, Any]) -> WorksResponse:
        results = [self._normalize_work(item) for item in (payload.get("results") or [])]
        meta = payload.get("meta") or {}
        return WorksResponse(
            total=meta.get("count"),
            next=meta.get("next_cursor"),
            data=results,
        )

    async def get_work(self, work_id: str) -> Work:
        clean_id = self._clean_openalex_id(work_id) or work_id
        payload = await self._fetch(f"/works/{clean_id}", {})
        return self._normalize_work(payload)

    async def get_citing_works(
        self,
        work_id: str,
        per_page: int | None = None,
        cursor: str | None = None,
    ) -> WorksResponse:
        clean_id = self._clean_openalex_id(work_id) or work_id
        params: dict[str, Any] = {
            "filter": f"cites:{clean_id}",
            "per_page": per_page or self.DEFAULT_PER_PAGE,
            "cursor": cursor,
        }
        payload = await self._fetch("/works", params)
        return self._to_works_response(payload)

    async def get_author_works(
        self,
        author_id: str,
        from_year: int | None = None,
        per_page: int | None = None,
    ) -> WorksResponse:
        clean_id = self._clean_openalex_id(author_id) or author_id
        filter_expr = f"author.id:{clean_id}"
        if from_year:
            filter_expr += f",from_publication_date:{from_year}-01-01"

        params: dict[str, Any] = {
            "filter": filter_expr,
            "per_page": per_page or self.DEFAULT_PER_PAGE,
            "sort": "publication_date:desc",
        }
        payload = await self._fetch("/works", params)
        return self._to_works_response(payload)

    async def search_by_doi(self, doi: str) -> Work | None:
        try:
            doi_url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
            encoded = quote(doi_url.replace("http://", "https://"), safe="")
            payload = await self._fetch(f"/works/{encoded}", {})
            return self._normalize_work(payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    async def search_by_title(self, title: str, per_page: int = 5) -> WorksResponse:
        payload = await self._fetch("/works", {"search": title, "per_page": per_page})
        return self._to_works_response(payload)

    async def search_paper_by_title(self, title: str) -> Work | None:
        response = await self.search_by_title(title, per_page=5)
        if not response.results:
            return None

        normalized_target = title.strip().lower()
        for work in response.results:
            if (work.title or "").strip().lower() == normalized_target:
                return work
        return response.results[0]

    async def get_works_batch(self, work_ids: list[str]) -> list[Work]:
        if not work_ids:
            return []

        clean_ids = [self._clean_openalex_id(x) or x for x in work_ids]
        results: list[Work] = []

        for i in range(0, len(clean_ids), self.MAX_BATCH_SIZE):
            batch = clean_ids[i : i + self.MAX_BATCH_SIZE]
            urls = [f"https://openalex.org/{wid}" for wid in batch]
            params = {
                "filter": f"ids.openalex:{'|'.join(urls)}",
                "per_page": len(batch),
            }
            try:
                payload = await self._fetch("/works", params)
                results.extend([self._normalize_work(item) for item in (payload.get("results") or [])])
            except httpx.HTTPError:
                for wid in batch:
                    try:
                        results.append(await self.get_work(wid))
                    except httpx.HTTPError:
                        continue

        return results

    # SemanticScholar-compatible wrappers used by engine/CLI
    async def get_paper_citations(self, paper_id: str, limit: int | None = None) -> WorksResponse:
        return await self.get_citing_works(paper_id, per_page=limit or self.DEFAULT_PER_PAGE)

    async def get_paper_references(self, paper_id: str, limit: int | None = None) -> WorksResponse:
        seed = await self.get_work(paper_id)
        refs = seed.referenced_works[: (limit or self.DEFAULT_PER_PAGE)]
        works = await self.get_works_batch(refs)
        return WorksResponse(total=len(works), data=works)

    async def get_author_papers(
        self,
        author_id: str,
        year: str | None = None,
        limit: int | None = None,
    ) -> WorksResponse:
        from_year: int | None = None
        if year:
            chunk = year.split("-")[0]
            if chunk.isdigit():
                from_year = int(chunk)
        return await self.get_author_works(
            author_id,
            from_year=from_year,
            per_page=limit or self.DEFAULT_PER_PAGE,
        )

