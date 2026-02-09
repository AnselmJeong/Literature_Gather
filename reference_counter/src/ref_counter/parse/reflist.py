from __future__ import annotations

import re

from ref_counter.models import CitationStyle, RefEntry

DOI_PATTERNS = [
    r"(?:doi[:\s]*)(10\.\d{4,9}/[^\s]+)",
    r"(?:https?://doi\.org/)(10\.\d{4,9}/[^\s]+)",
    r"(10\.\d{4,9}/[^\s]+)",
]


def parse_reference_list(ref_text: str, style: CitationStyle) -> list[RefEntry]:
    if style in (CitationStyle.NUMBERED_BRACKET, CitationStyle.NUMBERED_SUPERSCRIPT):
        return parse_numbered_references(ref_text)
    return parse_author_year_references(ref_text)


def parse_numbered_references(ref_text: str) -> list[RefEntry]:
    lines = [ln.strip() for ln in ref_text.splitlines() if ln.strip()]
    entries: list[tuple[int, str]] = []
    cur_num: int | None = None
    cur_text: list[str] = []

    for line in lines:
        m = re.match(r"^\[?(\d{1,4})\]?\.?\s+(.*)$", line)
        if m:
            if cur_num is not None:
                entries.append((cur_num, " ".join(cur_text).strip()))
            cur_num = int(m.group(1))
            cur_text = [m.group(2).strip()]
        elif cur_num is not None:
            cur_text.append(line)

    if cur_num is not None:
        entries.append((cur_num, " ".join(cur_text).strip()))

    return [_entry_from_raw(text, idx) for idx, text in entries]


def parse_author_year_references(ref_text: str) -> list[RefEntry]:
    lines = [ln.rstrip() for ln in ref_text.splitlines()]
    groups: list[str] = []
    cur: list[str] = []
    start_re = re.compile(r"^[A-Z][A-Za-z\-']+.*\(\d{4}[a-z]?\)")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if cur:
                groups.append(" ".join(cur).strip())
                cur = []
            continue
        if start_re.match(stripped) and cur:
            groups.append(" ".join(cur).strip())
            cur = [stripped]
        else:
            cur.append(stripped)
    if cur:
        groups.append(" ".join(cur).strip())

    return [_entry_from_raw(g, None) for g in groups if g]


def _entry_from_raw(raw: str, idx: int | None) -> RefEntry:
    doi = extract_doi(raw)
    year = extract_year(raw)
    authors = extract_authors(raw)
    title = extract_title(raw)
    journal = extract_journal(raw)
    return RefEntry(index=idx, authors=authors, year=year, title=title, journal=journal, doi=doi, raw_text=raw)


def extract_doi(text: str) -> str | None:
    for pat in DOI_PATTERNS:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).rstrip(".,);").lower()
    return None


def extract_year(text: str) -> int | None:
    m = re.search(r"\b(19\d{2}|20\d{2})[a-z]?\b", text)
    return int(m.group(1)) if m else None


def extract_authors(text: str) -> str:
    # Rough heuristic: before first year/period boundary
    m = re.search(r"\b(19\d{2}|20\d{2})[a-z]?\b", text)
    if m:
        prefix = text[: m.start()].strip(" .;")
        return prefix or "Unknown"
    return text.split(".")[0].strip() or "Unknown"


def extract_title(text: str) -> str:
    # Prefer segment between year and next period.
    y = re.search(r"\b(19\d{2}|20\d{2})[a-z]?\b", text)
    if y:
        rest = text[y.end() :].lstrip(" ).;:")
        first = rest.split(".")[0].strip()
        if len(first) >= 5:
            return first
    parts = [p.strip() for p in text.split(".") if p.strip()]
    return parts[1] if len(parts) > 1 else (parts[0] if parts else "Unknown title")


def extract_journal(text: str) -> str | None:
    parts = [p.strip() for p in text.split(".") if p.strip()]
    if len(parts) >= 3:
        j = parts[2]
        return j[:200] if j else None
    return None
