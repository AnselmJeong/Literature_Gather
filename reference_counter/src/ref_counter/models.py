from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class CitationStyle(str, Enum):
    NUMBERED_BRACKET = "numbered_bracket"
    NUMBERED_SUPERSCRIPT = "numbered_super"
    AUTHOR_YEAR = "author_year"


@dataclass(slots=True)
class TextBlock:
    text: str
    page: int
    font_size: float
    font_name: str
    is_superscript: bool
    bbox: tuple[float, float, float, float]


@dataclass(slots=True)
class SplitResult:
    body_text: str
    reference_text: str
    ref_start_page: int | None


@dataclass(slots=True)
class CitationEvent:
    ref_numbers: list[int]
    is_range: bool
    range_size: int
    raw_text: str
    page: int | None = None


@dataclass(slots=True)
class AuthorYearCitation:
    author_key: str
    year: str
    is_narrative: bool
    raw_text: str


@dataclass(slots=True)
class RefEntry:
    index: int | None
    authors: str
    year: int | None
    title: str
    journal: str | None
    doi: str | None
    raw_text: str


@dataclass(slots=True)
class ResolvedRef:
    openalex_id: str
    doi: str | None
    title: str
    authors: list[str]
    year: int | None
    journal: str | None
    cited_by_count: int | None
    oa_pdf_url: str | None
    resolution_confidence: float
    resolution_method: str


@dataclass(slots=True)
class RefFrequency:
    ref_number: int | None
    key: str
    in_text_count: int
    weighted_count: float
    entry: RefEntry
    resolved: ResolvedRef | None = None


@dataclass(slots=True)
class PaperIdentity:
    path: Path
    doi: str | None
    title: str | None


@dataclass(slots=True)
class SeedPaperResolved:
    openalex_id: str | None
    doi: str | None
    title: str | None


@dataclass(slots=True)
class PaperResult:
    source_pdf: str
    source_openalex_id: str | None
    source_doi: str | None
    citation_style: str
    total_references: int
    references_resolved: int
    references: list[RefFrequency] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
