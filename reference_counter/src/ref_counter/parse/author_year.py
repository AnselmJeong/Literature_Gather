from __future__ import annotations

import re
from collections import Counter

from ref_counter.models import AuthorYearCitation

PAREN_CIT_RE = re.compile(r"\(([^)]*\d{4}[a-z]?[^)]*)\)")
NARRATIVE_RE = re.compile(
    r"([A-Z][A-Za-z\-']+(?:\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z\-']+))?)\s*\((\d{4}[a-z]?)\)"
)


def parse_author_year_citations(body_text: str) -> list[AuthorYearCitation]:
    out: list[AuthorYearCitation] = []

    for m in PAREN_CIT_RE.finditer(body_text):
        inner = m.group(1)
        for chunk in inner.split(";"):
            item = _normalize_author_year(chunk)
            if item:
                out.append(
                    AuthorYearCitation(
                        author_key=item[0],
                        year=item[1],
                        is_narrative=False,
                        raw_text=chunk.strip(),
                    )
                )

    for m in NARRATIVE_RE.finditer(body_text):
        author = _normalize_author_text(m.group(1))
        year = m.group(2)
        if author:
            out.append(
                AuthorYearCitation(
                    author_key=author,
                    year=year,
                    is_narrative=True,
                    raw_text=m.group(0),
                )
            )

    return out


def aggregate_author_year(citations: list[AuthorYearCitation]) -> tuple[dict[str, int], dict[str, float]]:
    count = Counter()
    for c in citations:
        key = f"{c.author_key}_{c.year}"
        count[key] += 1
    weighted = {k: float(v) for k, v in count.items()}
    return dict(count), weighted


def _normalize_author_year(citation: str) -> tuple[str, str] | None:
    # supports: Smith et al., 2020 / Smith & Lee, 2019 / Smith, 2018a
    m = re.search(r"([A-Z][A-Za-z\-']+(?:\s+(?:et\s+al\.?|&\s*[A-Z][A-Za-z\-']+|and\s+[A-Z][A-Za-z\-']+))?)\s*,?\s*(\d{4}[a-z]?)", citation)
    if not m:
        return None
    return _normalize_author_text(m.group(1)), m.group(2)


def _normalize_author_text(author: str) -> str:
    cleaned = re.sub(r"\s+", " ", author).strip().replace(".", "")
    return cleaned
