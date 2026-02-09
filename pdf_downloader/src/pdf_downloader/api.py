"""Batch download API for OpenAlex work IDs."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import requests

API_BASE = "https://api.openalex.org"
CONTENT_BASE = "https://content.openalex.org"


@dataclass
class DownloadFailure:
    openalex_id: str
    title: str | None
    doi: str | None
    reason: str
    oa_status: str | None = None
    landing_page_url: str | None = None
    candidate_urls: list[str] = field(default_factory=list)


@dataclass
class BatchDownloadResult:
    total: int
    success: int
    failed: int
    skipped: int
    failures: list[DownloadFailure] = field(default_factory=list)
    downloaded_paths: dict[str, str] = field(default_factory=dict)


def _extract_openalex_id(value: str) -> str | None:
    if not value:
        return None
    match = re.search(r"W\d+", value)
    return match.group(0) if match else None


def _normalize_openalex_ids(openalex_ids: set[str] | list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in openalex_ids:
        wid = _extract_openalex_id(str(raw).strip())
        if not wid or wid in seen:
            continue
        seen.add(wid)
        out.append(wid)
    return out


def _get_work(work_id: str, api_key: str | None) -> dict | None:
    headers = {"Accept": "application/json"}
    params = {}
    if api_key:
        params["api_key"] = api_key
    try:
        response = requests.get(
            f"{API_BASE}/works/{quote(work_id, safe='')}",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def _extract_candidate_urls(work: dict, api_key: str | None) -> tuple[list[str], str | None]:
    candidates: list[str] = []
    landing_page = None

    work_id = work.get("id", "")
    openalex_id = _extract_openalex_id(work_id)
    if api_key and openalex_id:
        candidates.append(f"{CONTENT_BASE}/works/{openalex_id}.pdf")

    best_oa = work.get("best_oa_location") or {}
    if best_oa.get("pdf_url"):
        candidates.append(best_oa["pdf_url"])
    if best_oa.get("landing_page_url") and not landing_page:
        landing_page = best_oa["landing_page_url"]

    primary_loc = work.get("primary_location") or {}
    if primary_loc.get("pdf_url"):
        candidates.append(primary_loc["pdf_url"])
    if primary_loc.get("landing_page_url") and not landing_page:
        landing_page = primary_loc["landing_page_url"]

    for loc in work.get("locations", []) or []:
        if not isinstance(loc, dict):
            continue
        if loc.get("pdf_url"):
            candidates.append(loc["pdf_url"])
        if loc.get("landing_page_url") and not landing_page:
            landing_page = loc["landing_page_url"]

    deduped: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if url and url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped, landing_page


def _filename_for(work: dict) -> str:
    year = work.get("publication_year", "Unknown")
    title = (work.get("title") or "Untitled").replace(":", ";")
    title = re.sub(r'[<>"/\\|?*]', "", title).strip()
    title = re.sub(r"\s+", " ", title)

    authors = []
    for auth in work.get("authorships", []) or []:
        name = (auth.get("author") or {}).get("display_name", "")
        if name:
            authors.append(name.split()[-1])
    if not authors:
        author_text = "Unknown"
    elif len(authors) == 1:
        author_text = authors[0]
    elif len(authors) == 2:
        author_text = f"{authors[0]}, {authors[1]}"
    else:
        author_text = f"{authors[0]} et al."

    filename = f"{year} - {author_text} - {title}.pdf"
    if len(filename) > 220:
        filename = filename[:216] + ".pdf"
    return filename


def _download_pdf(url: str, filepath: Path, api_key: str | None, use_content_api: bool) -> tuple[bool, str | None]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/pdf,application/x-pdf,*/*",
    }
    if use_content_api and api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.get(url, stream=True, timeout=120, headers=headers)
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}"

        content_type = response.headers.get("content-type", "").lower()
        if "pdf" not in content_type and "application/octet-stream" not in content_type:
            if response.content[:4] != b"%PDF":
                return False, f"Not a PDF (content-type={content_type})"

        with filepath.open("wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True, None
    except requests.RequestException as exc:
        return False, str(exc)


def download_openalex_ids(
    openalex_ids: set[str] | list[str],
    *,
    output_dir: str | Path,
    skip_existing: bool = True,
    delay: float = 0.0,
    api_key: str | None = None,
) -> BatchDownloadResult:
    """Download PDFs from a set of OpenAlex IDs."""
    api_key = api_key or os.getenv("OPENALEX_API_KEY")
    normalized_ids = _normalize_openalex_ids(openalex_ids)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    success = 0
    failed = 0
    skipped = 0
    failures: list[DownloadFailure] = []
    downloaded_paths: dict[str, str] = {}

    for idx, work_id in enumerate(normalized_ids):
        work = _get_work(work_id, api_key)
        if not work:
            failed += 1
            failures.append(
                DownloadFailure(
                    openalex_id=work_id,
                    title=None,
                    doi=None,
                    reason="Failed to fetch OpenAlex work metadata",
                )
            )
            continue

        filename = _filename_for(work)
        filepath = out_dir / filename
        if skip_existing and filepath.exists():
            skipped += 1
            downloaded_paths[work_id] = str(filepath)
            continue

        candidate_urls, landing_page = _extract_candidate_urls(work, api_key)
        oa_status = (work.get("open_access") or {}).get("oa_status")
        doi = work.get("doi")
        if isinstance(doi, str):
            doi = doi.replace("https://doi.org/", "")

        if not candidate_urls:
            failed += 1
            failures.append(
                DownloadFailure(
                    openalex_id=work_id,
                    title=work.get("title"),
                    doi=doi,
                    reason="No open access PDF URL available",
                    oa_status=oa_status,
                    landing_page_url=landing_page,
                    candidate_urls=[],
                )
            )
            continue

        done = False
        last_err = None
        for url in candidate_urls:
            use_content_api = "content.openalex.org/works/" in url
            ok, err = _download_pdf(url, filepath, api_key, use_content_api)
            if ok:
                done = True
                break
            last_err = err

        if done:
            success += 1
            downloaded_paths[work_id] = str(filepath)
        else:
            failed += 1
            failures.append(
                DownloadFailure(
                    openalex_id=work_id,
                    title=work.get("title"),
                    doi=doi,
                    reason=f"All candidate download attempts failed: {last_err or 'unknown'}",
                    oa_status=oa_status,
                    landing_page_url=landing_page,
                    candidate_urls=candidate_urls,
                )
            )

        if delay > 0 and idx < len(normalized_ids) - 1:
            time.sleep(delay)

    return BatchDownloadResult(
        total=len(normalized_ids),
        success=success,
        failed=failed,
        skipped=skipped,
        failures=failures,
        downloaded_paths=downloaded_paths,
    )
