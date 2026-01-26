from __future__ import annotations

import argparse
import datetime as dt
import difflib
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import bibtexparser
import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

UNPAYWALL_EMAIL = "anselmjeong@gmail.com"
UNPAYWALL_API_BASE = "https://api.unpaywall.org/v2"
CRS_API_BASE = "https://api.crossref.org/works"
DEFAULT_OUTPUT_DIR = "./article_downloaded"
DEFAULT_REPORT_FILE = "download_failed_report.html"
DEFAULT_PROGRESS_EVERY = 25
DEFAULT_MIN_PUBYEAR = 2010


@dataclass
class BibEntry:
    title: str
    authors: str
    year: str
    doi: str | None


@dataclass
class FailedItem:
    title: str
    authors: str
    year: str
    doi: str | None
    reason: str
    landing_page_url: str | None = None
    candidate_pdf_urls: list[str] = field(default_factory=list)
    unpaywall_json: dict[str, Any] | None = None


@dataclass
class SkippedItem:
    title: str
    authors: str
    year: str
    doi: str | None
    reason: str


def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _clean_doi(doi: str) -> str:
    doi = doi.strip()
    doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    doi = doi.removeprefix("doi:").strip()
    return doi


def _unpaywall_landing_page(doi: str) -> str:
    # Unpaywall landing page format (always useful even when PDF is missing)
    # Keep '/' unescaped to match common DOI URL patterns.
    return f"https://unpaywall.org/doi/{quote(doi, safe='/')}"


def _doi_url(doi: str) -> str:
    return f"https://doi.org/{quote(doi, safe='/')}"


def _parse_year_int(year: str) -> int | None:
    y = (year or "").strip()
    if not y or y.upper() in {"NA", "N/A"}:
        return None
    # Try plain int first
    try:
        yy = int(y)
        if 1000 <= yy <= 3000:
            return yy
    except ValueError:
        pass
    # Extract 4-digit year anywhere
    m = re.search(r"\b(1[0-9]{3}|20[0-9]{2}|21[0-9]{2})\b", y)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _norm_for_match(title: str) -> str:
    t = (title or "").lower()
    t = t.replace("{", "").replace("}", "")
    t = re.sub(r"\\[a-zA-Z]+\b", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return _normalize_space(t)


def lookup_doi_via_crossref(
    session: requests.Session,
    *,
    title: str,
    authors: str,
    year: str,
    cache: dict[str, str | None],
    max_attempts: int = 3,
    timeout_s: float = 15.0,
    verbose: bool = False,
) -> tuple[str | None, str | None]:
    """
    Title-based DOI lookup using Crossref.
    Returns (doi, error_message). If not found, doi=None and error_message explains why.
    """
    norm_title = _norm_for_match(title)
    if not norm_title or norm_title == "unknown":
        return None, "Missing title — cannot query Crossref."

    if norm_title in cache:
        return cache[norm_title], None

    headers = {
        "User-Agent": f"article-downloader/0.1.0 (mailto:{UNPAYWALL_EMAIL})",
        "Accept": "application/json",
    }
    params = {"query.bibliographic": title, "rows": 5}

    last_err: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = session.get(CRS_API_BASE, params=params, headers=headers, timeout=timeout_s)
            if r.status_code == 429:
                last_err = "Rate limited (HTTP 429)"
                sleep_s = 1.0 * (2 ** (attempt - 1))
                if verbose:
                    print(f"[Crossref] 레이트리밋, 대기 {sleep_s:.1f}s", flush=True)
                time.sleep(sleep_s)
                continue
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                if verbose:
                    print(f"[Crossref] 실패 {last_err}", flush=True)
            else:
                data = r.json()
                items = (((data or {}).get("message") or {}).get("items")) or []
                best_doi: str | None = None
                best_score = 0.0
                target_year = _parse_year_int(year)

                for it in items:
                    if not isinstance(it, dict):
                        continue
                    doi = it.get("DOI")
                    if not isinstance(doi, str) or not doi.strip():
                        continue
                    cand_titles = it.get("title") or []
                    cand_title = cand_titles[0] if isinstance(cand_titles, list) and cand_titles else ""
                    cand_norm = _norm_for_match(str(cand_title))
                    if not cand_norm:
                        continue

                    title_ratio = difflib.SequenceMatcher(None, norm_title, cand_norm).ratio()
                    score = title_ratio

                    # Year agreement bonus/penalty (if we have a year)
                    if target_year is not None:
                        issued = it.get("issued") or {}
                        parts = issued.get("date-parts") if isinstance(issued, dict) else None
                        cand_year: int | None = None
                        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
                            try:
                                cand_year = int(parts[0][0])
                            except Exception:
                                cand_year = None
                        if cand_year is not None:
                            diff = abs(cand_year - target_year)
                            if diff <= 1:
                                score += 0.06
                            elif diff >= 5:
                                score -= 0.08

                    if score > best_score:
                        best_score = score
                        best_doi = _clean_doi(doi)

                # Accept only if similarity is decent
                if best_doi and best_score >= 0.78:
                    cache[norm_title] = best_doi
                    if verbose:
                        print(f"[Crossref] DOI 발견: {best_doi} (score={best_score:.2f})", flush=True)
                    return best_doi, None

                cache[norm_title] = None
                return None, "No confident DOI match from Crossref."
        except requests.RequestException as ex:
            last_err = f"{type(ex).__name__}: {ex}"
            if verbose:
                print(f"[Crossref] 예외 {last_err}", flush=True)

        if attempt < max_attempts:
            time.sleep(0.6 * (2 ** (attempt - 1)))

    cache[norm_title] = None
    return None, f"Crossref failed after retries: {last_err or 'Unknown'}"


def _first_author_lastname(authors: str) -> str:
    # BibTeX author format often: "Last, First and Last2, First2"
    a = authors or ""
    parts = [p.strip() for p in a.split(" and ") if p.strip()]
    if not parts:
        return "Unknown"
    first = parts[0]
    if "," in first:
        return _normalize_space(first.split(",", 1)[0]) or "Unknown"
    tokens = [t for t in re.split(r"\s+", first) if t]
    return tokens[-1] if tokens else "Unknown"


def _short_title(title: str, max_len: int = 60) -> str:
    t = title or "Unknown"
    # remove common BibTeX/LaTeX wrappers
    t = t.replace("{", "").replace("}", "")
    t = re.sub(r"\\[a-zA-Z]+\b", "", t)  # drop latex commands
    t = _normalize_space(t)
    if len(t) > max_len:
        t = t[:max_len].rstrip()
    return t


_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')


def _safe_filename_component(s: str) -> str:
    s = _normalize_space(s)
    s = _UNSAFE_FILENAME_CHARS.sub("_", s)
    s = re.sub(r"[^\w\-\. ]+", "_", s, flags=re.UNICODE)
    s = s.replace(" ", "_")
    s = re.sub(r"_+", "_", s).strip("_.")
    return s or "Unknown"


def build_pdf_filename(year: str, authors: str, title: str, max_total_len: int = 120) -> str:
    y = _safe_filename_component(year or "NA")
    a = _safe_filename_component(_first_author_lastname(authors))
    t = _safe_filename_component(_short_title(title))
    base = f"{y}_{a}_{t}"
    # enforce max length including ".pdf"
    suffix = ".pdf"
    if len(base) + len(suffix) > max_total_len:
        base = base[: max_total_len - len(suffix)].rstrip("._")
    return base + suffix


def parse_bibtex_file(bib_path: str) -> list[BibEntry]:
    with open(bib_path, "r", encoding="utf-8") as f:
        bib = bibtexparser.load(f)

    entries: list[BibEntry] = []
    for e in bib.entries:
        title = _normalize_space(e.get("title", "")) or "Unknown"
        authors = _normalize_space(e.get("author", "")) or "Unknown"
        year = _normalize_space(e.get("year", "")) or "NA"
        doi_raw = e.get("doi")
        doi = _clean_doi(str(doi_raw)) if doi_raw else None
        if doi == "":
            doi = None
        entries.append(BibEntry(title=title, authors=authors, year=year, doi=doi))
    return entries


def _pick_pdf_urls(unpaywall_json: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    best = unpaywall_json.get("best_oa_location") or {}
    best_pdf = best.get("url_for_pdf")
    if isinstance(best_pdf, str) and best_pdf.strip():
        urls.append(best_pdf.strip())
    for loc in unpaywall_json.get("oa_locations") or []:
        if not isinstance(loc, dict):
            continue
        u = loc.get("url_for_pdf")
        if isinstance(u, str) and u.strip():
            urls.append(u.strip())
    # de-dupe while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


def query_unpaywall(
    session: requests.Session,
    doi: str,
    *,
    max_attempts: int = 3,
    timeout_s: float = 15.0,
    verbose: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    # Keep '/' unescaped; Unpaywall commonly accepts DOI with slash in the path.
    url = f"{UNPAYWALL_API_BASE}/{quote(doi, safe='/')}"
    params = {"email": UNPAYWALL_EMAIL}

    last_err: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = session.get(url, params=params, timeout=timeout_s)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                if verbose:
                    print(f"[Unpaywall] 실패 ({doi}) {last_err}")
            else:
                return r.json(), None
        except requests.RequestException as ex:
            last_err = f"{type(ex).__name__}: {ex}"
            if verbose:
                print(f"[Unpaywall] 예외 ({doi}) {last_err}")

        if attempt < max_attempts:
            sleep_s = 0.6 * (2 ** (attempt - 1))
            time.sleep(sleep_s)
    return None, last_err


def _looks_like_pdf(headers: dict[str, str], first_bytes: bytes) -> bool:
    ct = (headers.get("Content-Type") or "").lower()
    if "application/pdf" in ct:
        return True
    # Some OA hosts serve PDFs with generic octet-stream; validate by magic.
    if first_bytes.startswith(b"%PDF-"):
        return True
    # Fall back: accept if content-type mentions pdf
    if "pdf" in ct:
        return True
    return False


def download_pdf(
    session: requests.Session,
    pdf_url: str,
    save_path: str,
    *,
    timeout_s: float = 30.0,
    verbose: bool = False,
) -> tuple[bool, str | None]:
    try:
        with session.get(pdf_url, stream=True, timeout=timeout_s, allow_redirects=True) as r:
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}"

            it = r.iter_content(chunk_size=64 * 1024)
            try:
                first_chunk = next(it)
            except StopIteration:
                return False, "Empty response"

            if not _looks_like_pdf(dict(r.headers), first_chunk[:8]):
                return False, f"Not a PDF (Content-Type={r.headers.get('Content-Type')})"

            os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(first_chunk)
                for chunk in it:
                    if chunk:
                        f.write(chunk)

        if verbose:
            print(f"[다운로드] 저장 완료: {save_path}")
        return True, None
    except requests.RequestException as ex:
        return False, f"{type(ex).__name__}: {ex}"


def render_failure_report_html(
    failures: list[FailedItem],
    skipped: list[SkippedItem],
    *,
    success_count: int,
    total_count: int,
    report_path: str,
    output_dir: str,
    dry_run: bool,
    min_pubyear: int,
) -> None:
    now = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    fail_count = len(failures)
    skipped_count = len(skipped)
    mode = "DRY-RUN" if dry_run else "DOWNLOAD"

    def link(url: str, text: str | None = None) -> str:
        safe_url = html.escape(url, quote=True)
        safe_text = html.escape(text or url)
        return f'<a href="{safe_url}" target="_blank" rel="noreferrer">{safe_text}</a>'

    rows: list[str] = []
    for f in failures:
        doi = html.escape(f.doi or "")
        doi_link = link(_doi_url(f.doi), "doi.org") if f.doi else ""
        title = html.escape(f.title)
        authors = html.escape(f.authors)
        year = html.escape(f.year)
        reason = html.escape(f.reason)
        pdf_links = "<br/>".join(link(u, "PDF") for u in f.candidate_pdf_urls) if f.candidate_pdf_urls else ""
        raw_json = (
            "<details><summary>Raw JSON</summary><pre>"
            + html.escape(json.dumps(f.unpaywall_json, ensure_ascii=False, indent=2))
            + "</pre></details>"
            if f.unpaywall_json
            else ""
        )

        rows.append(
            "<tr>"
            f"<td>{title}</td>"
            f"<td>{authors}</td>"
            f"<td>{year}</td>"
            f"<td>{doi}</td>"
            f"<td>{reason}</td>"
            f"<td>{doi_link}</td>"
            f"<td>{pdf_links}</td>"
            f"<td>{raw_json}</td>"
            "</tr>"
        )

    skipped_rows: list[str] = []
    for s in skipped:
        doi = html.escape(s.doi or "")
        doi_link = link(_doi_url(s.doi), "doi.org") if s.doi else ""
        title = html.escape(s.title)
        authors = html.escape(s.authors)
        year = html.escape(s.year)
        reason = html.escape(s.reason)
        skipped_rows.append(
            "<tr>"
            f"<td>{title}</td>"
            f"<td>{authors}</td>"
            f"<td>{year}</td>"
            f"<td>{doi}</td>"
            f"<td>{doi_link}</td>"
            f"<td>{reason}</td>"
            "</tr>"
        )

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Download Failed Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 24px; }}
    .meta {{ color: #444; margin-bottom: 16px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #f2f2f2; text-align: left; }}
    tr:nth-child(even) {{ background: #fafafa; }}
    code {{ background: #f6f6f6; padding: 2px 4px; border-radius: 4px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; margin: 8px 0 0; }}
    details > summary {{ cursor: pointer; }}
  </style>
</head>
<body>
  <h2>Download Failed Report</h2>
  <div class="meta">
    <div><b>Timestamp</b>: {html.escape(now)}</div>
    <div><b>Mode</b>: {html.escape(mode)}</div>
    <div><b>Total</b>: {total_count} / <b>Success</b>: {success_count} / <b>Failed</b>: {fail_count} / <b>Skipped</b>: {skipped_count}</div>
    <div><b>Min PubYear</b>: {min_pubyear} (year missing/unparseable → not filtered)</div>
    <div><b>Output</b>: <code>{html.escape(output_dir)}</code></div>
  </div>

  <h3>Failed Entries</h3>
  <table>
    <thead>
      <tr>
        <th>Title</th>
        <th>Authors</th>
        <th>Year</th>
        <th>DOI</th>
        <th>Reason</th>
        <th>DOI Link</th>
        <th>Candidate PDF URLs</th>
        <th>Raw Unpaywall JSON</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>

  <h3>Skipped (Filtered by Min PubYear)</h3>
  <table>
    <thead>
      <tr>
        <th>Title</th>
        <th>Authors</th>
        <th>Year</th>
        <th>DOI</th>
        <th>DOI Link</th>
        <th>Reason</th>
      </tr>
    </thead>
    <tbody>
      {"".join(skipped_rows)}
    </tbody>
  </table>
</body>
</html>
"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_doc)


def run(
    bib_path: str,
    *,
    output_dir: str,
    report_file: str,
    verbose: bool,
    dry_run: bool,
    min_pubyear: int,
) -> int:
    # Improve UX: ensure logs show up promptly even when stdout is buffered.
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass

    console = Console()

    if not os.path.exists(bib_path):
        console.print(f"[red][오류][/red] 입력 파일이 존재하지 않습니다: {bib_path}")
        return 2
    if not bib_path.lower().endswith(".bib"):
        console.print(f"[red][오류][/red] .bib 파일만 지원합니다: {bib_path}")
        return 2

    entries = parse_bibtex_file(bib_path)
    total = len(entries)
    failures: list[FailedItem] = []
    skipped: list[SkippedItem] = []
    success = 0

    console.print(
        f"[cyan][시작][/cyan] entries={total}, dry_run={dry_run}, output_dir={output_dir}, report={report_file}, min_pubyear={min_pubyear}"
    )

    os.makedirs(output_dir, exist_ok=True)
    with requests.Session() as session:
        crossref_cache: dict[str, str | None] = {}
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]처리 중...", total=total)
            for idx, e in enumerate(entries, start=1):
                # Min pubyear filter (year missing/unparseable -> NOT filtered)
                y_int = _parse_year_int(e.year)
                if y_int is not None and y_int < min_pubyear:
                    skipped.append(
                        SkippedItem(
                            title=e.title,
                            authors=e.authors,
                            year=e.year,
                            doi=e.doi,
                            reason=f"Filtered out: year {y_int} < min_pubyear {min_pubyear}",
                        )
                    )
                    if verbose:
                        print(f"[SKIP] {e.year} < {min_pubyear}: {e.title}", flush=True)
                    progress.update(task, completed=idx, description=f"[cyan]처리 중... ({idx}/{total})")
                    continue

                doi = e.doi
                if not doi:
                    if verbose:
                        print(f"[Crossref] DOI 없음 → 제목으로 탐색: {e.title}", flush=True)
                    doi, cr_err = lookup_doi_via_crossref(
                        session,
                        title=e.title,
                        authors=e.authors,
                        year=e.year,
                        cache=crossref_cache,
                        verbose=verbose,
                    )
                    if not doi:
                        failures.append(
                            FailedItem(
                                title=e.title,
                                authors=e.authors,
                                year=e.year,
                                doi=None,
                                reason=f"No DOI in BibTeX and Crossref lookup failed: {cr_err or 'Unknown'}",
                            )
                        )
                        progress.update(task, completed=idx, description=f"[cyan]처리 중... ({idx}/{total})")
                        continue

                if verbose:
                    print(f"[Unpaywall] 조회: {doi}", flush=True)
                data, err = query_unpaywall(session, doi, verbose=verbose)
                if data is None:
                    failures.append(
                        FailedItem(
                            title=e.title,
                            authors=e.authors,
                            year=e.year,
                            doi=doi,
                            reason=f"Unpaywall API failed after retries: {err or 'Unknown error'}",
                        )
                    )
                    progress.update(task, completed=idx, description=f"[cyan]처리 중... ({idx}/{total})")
                    continue

                pdf_urls = _pick_pdf_urls(data)
                if not pdf_urls:
                    failures.append(
                        FailedItem(
                            title=e.title,
                            authors=e.authors,
                            year=e.year,
                            doi=doi,
                            reason="No OA PDF URL available in Unpaywall response.",
                            candidate_pdf_urls=[],
                            unpaywall_json=data,
                        )
                    )
                    progress.update(task, completed=idx, description=f"[cyan]처리 중... ({idx}/{total})")
                    continue

                if dry_run:
                    # In dry-run, treat OA-available as success (no download performed).
                    success += 1
                    if verbose:
                        print(f"[DRY-RUN] OA PDF 후보 {len(pdf_urls)}개 발견: {doi}", flush=True)
                    progress.update(task, completed=idx, description=f"[cyan]처리 중... ({idx}/{total})")
                    continue

                filename = build_pdf_filename(e.year, e.authors, e.title)
                save_path = os.path.join(output_dir, filename)

                ok = False
                dl_err: str | None = None
                for u in pdf_urls:
                    if verbose:
                        print(f"[다운로드] 시도: {u}", flush=True)
                    ok, dl_err = download_pdf(session, u, save_path, verbose=verbose)
                    if ok:
                        break

                if ok:
                    success += 1
                else:
                    failures.append(
                        FailedItem(
                            title=e.title,
                            authors=e.authors,
                            year=e.year,
                            doi=doi,
                            reason=f"PDF download failed or not a PDF: {dl_err or 'Unknown'}",
                            candidate_pdf_urls=pdf_urls,
                            unpaywall_json=data,
                        )
                    )
                progress.update(task, completed=idx, description=f"[cyan]처리 중... ({idx}/{total})")

    render_failure_report_html(
        failures,
        skipped,
        success_count=success,
        total_count=total,
        report_path=report_file,
        output_dir=output_dir,
        dry_run=dry_run,
        min_pubyear=min_pubyear,
    )

    # 최종 요약 테이블
    table = Table(title="[bold green]다운로드 완료", show_header=True, header_style="bold magenta")
    table.add_column("항목", style="cyan", no_wrap=True)
    table.add_column("개수", style="yellow", justify="right")
    table.add_column("비율", style="green", justify="right")
    
    table.add_row("전체", str(total), "100.0%")
    table.add_row("[green]성공", str(success), f"{success/total*100:.1f}%" if total > 0 else "0.0%")
    table.add_row("[red]실패", str(len(failures)), f"{len(failures)/total*100:.1f}%" if total > 0 else "0.0%")
    table.add_row("[yellow]스킵", str(len(skipped)), f"{len(skipped)/total*100:.1f}%" if total > 0 else "0.0%")
    
    console.print()
    console.print(table)
    console.print(f"[cyan][리포트][/cyan] {os.path.abspath(report_file)}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    description = """BibTeX(.bib) 파일에서 DOI를 추출하여 Unpaywall API를 통해 Open Access PDF를 자동으로 다운로드합니다.

이 도구는 다음과 같은 기능을 제공합니다:
  • BibTeX 파일에서 DOI 자동 추출
  • DOI가 없는 경우 Crossref API를 통한 제목 기반 DOI 탐색
  • Unpaywall API를 통한 Open Access PDF URL 조회
  • PDF 자동 다운로드 및 파일명 정리
  • 실패한 항목에 대한 상세 HTML 리포트 생성

출력 파일명 형식: {연도}_{첫저자성}_{제목}.pdf
"""
    
    epilog = """사용 예시:

  # 기본 사용 (2010년 이후 논문만 다운로드)
  bib-dl library.bib

  # 특정 연도 이후 논문만 다운로드
  bib-dl library.bib --min-pubyear 2015

  # 출력 폴더와 리포트 파일명 지정
  bib-dl library.bib --output ./pdfs --report failed.html

  # 상세 로그 출력
  bib-dl library.bib --verbose

  # 다운로드 없이 OA 가능 여부만 확인 (dry-run)
  bib-dl library.bib --dry-run

  # 모든 옵션 조합
  bib-dl library.bib --output ./articles --min-pubyear 2018 --verbose --dry-run
"""
    
    p = argparse.ArgumentParser(
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "bibfile",
        help="입력 BibTeX 파일 경로 (.bib 확장자 필요)",
        metavar="BIBFILE",
    )
    p.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help=f"PDF 저장 폴더 경로 (기본값: {DEFAULT_OUTPUT_DIR})",
    )
    p.add_argument(
        "--report",
        default=DEFAULT_REPORT_FILE,
        metavar="FILE",
        help=f"실패 항목 HTML 리포트 파일명 (기본값: {DEFAULT_REPORT_FILE})",
    )
    p.add_argument(
        "--min-pubyear",
        type=int,
        default=DEFAULT_MIN_PUBYEAR,
        metavar="YEAR",
        help=(
            f"이 연도(포함) 이후 출판된 논문만 다운로드합니다 (기본값: {DEFAULT_MIN_PUBYEAR}). "
            "연도가 비어있거나 파싱 불가능한 경우 필터 예외로 처리되어 다운로드를 시도합니다."
        ),
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="상세한 로그를 출력합니다. Crossref DOI 탐색, Unpaywall 조회, 다운로드 시도 등의 과정을 모두 표시합니다.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="실제로 PDF를 다운로드하지 않고, Open Access PDF가 사용 가능한지만 확인합니다. 리포트는 정상적으로 생성됩니다.",
    )
    return p


def main() -> int:
    args = build_arg_parser().parse_args()
    return run(
        args.bibfile,
        output_dir=args.output,
        report_file=args.report,
        verbose=args.verbose,
        dry_run=args.dry_run,
        min_pubyear=args.min_pubyear,
    )


if __name__ == "__main__":
    raise SystemExit(main())
