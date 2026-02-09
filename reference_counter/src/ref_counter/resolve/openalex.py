from __future__ import annotations

import asyncio
from dataclasses import asdict

import aiohttp
from aiolimiter import AsyncLimiter

from ref_counter.models import RefEntry, ResolvedRef
from ref_counter.resolve.cache import ResolutionCache
from ref_counter.resolve.matcher import best_match


class OpenAlexClient:
    BASE = "https://api.openalex.org"

    def __init__(
        self,
        api_key: str,
        concurrency: int = 5,
        cache: ResolutionCache | None = None,
    ):
        self.api_key = api_key
        self.semaphore = asyncio.Semaphore(concurrency)
        self.limiter = AsyncLimiter(90, 1)
        self.cache = cache or ResolutionCache()
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "OpenAlexClient":
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session:
            await self._session.close()

    async def resolve_ref(self, entry: RefEntry) -> ResolvedRef | None:
        if entry.doi:
            key = f"doi:{entry.doi.lower()}"
            cached = self.cache.get(key)
            if cached:
                return ResolvedRef(**cached)

            work = await self._fetch_work(f"/works/doi:{entry.doi}")
            if work:
                resolved = _to_resolved(work, 1.0, "doi_exact")
                self.cache.set(key, asdict(resolved))
                return resolved

        title_key = f"title:{(entry.title or '').lower()}:{entry.year or ''}"
        cached = self.cache.get(title_key)
        if cached:
            return ResolvedRef(**cached)

        candidates = await self.search_works(entry.title, entry.year)
        cand, score = best_match(entry, candidates)
        if not cand or score < 0.70:
            return None

        method = "title_fuzzy"
        if score >= 0.95:
            method = "title_exact_year"
        resolved = _to_resolved(cand, score, method)
        self.cache.set(title_key, asdict(resolved))
        return resolved

    async def identify_seed(self, doi: str | None, title: str | None) -> tuple[str | None, str | None]:
        if doi:
            work = await self._fetch_work(f"/works/doi:{doi}")
            if work:
                return work.get("id"), work.get("doi")
        if title:
            candidates = await self.search_works(title, None)
            if candidates:
                return candidates[0].get("id"), candidates[0].get("doi")
        return None, doi

    async def search_works(self, title: str, year: int | None) -> list[dict]:
        if not title:
            return []
        params = {
            "search": title,
            "api_key": self.api_key,
            "per_page": "10",
            "select": "id,doi,display_name,title,publication_year,cited_by_count,authorships,primary_location,best_oa_location",
        }
        if year:
            params["filter"] = f"publication_year:{year}"
        data = await self._get_json("/works", params=params)
        return data.get("results", []) if data else []

    async def _fetch_work(self, path: str) -> dict | None:
        params = {"api_key": self.api_key}
        return await self._get_json(path, params=params)

    async def _get_json(self, path: str, params: dict[str, str] | None = None, retries: int = 3) -> dict | None:
        if self._session is None:
            raise RuntimeError("OpenAlexClient session not initialized")
        url = f"{self.BASE}{path}"
        for attempt in range(retries):
            async with self.semaphore:
                async with self.limiter:
                    try:
                        async with self._session.get(url, params=params) as resp:
                            if resp.status == 404:
                                return None
                            if resp.status == 429:
                                await asyncio.sleep(2**attempt)
                                continue
                            resp.raise_for_status()
                            return await resp.json()
                    except aiohttp.ClientError:
                        if attempt == retries - 1:
                            return None
                        await asyncio.sleep(2**attempt)
        return None


def _to_resolved(work: dict, confidence: float, method: str) -> ResolvedRef:
    auths = []
    for a in work.get("authorships", [])[:10]:
        nm = ((a.get("author") or {}).get("display_name") or "").strip()
        if nm:
            auths.append(nm)

    oa = work.get("best_oa_location") or work.get("primary_location") or {}
    source = oa.get("source") or {}
    return ResolvedRef(
        openalex_id=(work.get("id") or "").replace("https://openalex.org/", ""),
        doi=(work.get("doi") or "").replace("https://doi.org/", "") or None,
        title=work.get("display_name") or work.get("title") or "",
        authors=auths,
        year=work.get("publication_year"),
        journal=source.get("display_name") if isinstance(source, dict) else None,
        cited_by_count=work.get("cited_by_count"),
        oa_pdf_url=oa.get("pdf_url"),
        resolution_confidence=confidence,
        resolution_method=method,
    )
