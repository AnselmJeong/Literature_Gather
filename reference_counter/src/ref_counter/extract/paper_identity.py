from __future__ import annotations

import re
from pathlib import Path

import fitz

from ref_counter.models import PaperIdentity

DOI_PAT = re.compile(r"(?:doi[:\s]*|https?://doi\.org/)?(10\.\d{4,9}/\S+)", re.IGNORECASE)


def identify_pdf(pdf_path: str | Path) -> PaperIdentity:
    path = Path(pdf_path)
    doi = None
    title = None

    with fitz.open(path) as doc:
        md = doc.metadata or {}
        doi = _clean_doi(md.get("doi")) if md.get("doi") else None
        title = (md.get("title") or "").strip() or None

        first_page = doc[0].get_text("text") if len(doc) else ""
        if not doi:
            doi = _find_doi(first_page)
        if not title:
            title = _guess_title(doc)

    return PaperIdentity(path=path, doi=doi, title=title)


def _find_doi(text: str) -> str | None:
    m = DOI_PAT.search(text)
    return _clean_doi(m.group(1)) if m else None


def _clean_doi(s: str | None) -> str | None:
    if not s:
        return None
    return s.strip().rstrip(".;,)").lower()


def _guess_title(doc: fitz.Document) -> str | None:
    if not len(doc):
        return None
    spans: list[tuple[float, str]] = []
    for block in doc[0].get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = (span.get("text") or "").strip()
                if len(txt) < 8:
                    continue
                spans.append((float(span.get("size", 0.0)), txt))
    if not spans:
        return None
    max_size = max(s for s, _ in spans)
    candidates = [t for s, t in spans if s >= max_size * 0.95]
    if not candidates:
        return None
    joined = " ".join(candidates).strip()
    return re.sub(r"\s+", " ", joined)[:400] or None
