"""Pydantic models for Citation Snowball application."""
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ============================================================================
# Enums
# ============================================================================


class DiscoveryMethod(str, Enum):
    """How a paper was discovered."""

    SEED = "seed"
    FORWARD = "forward"  # Citing works
    BACKWARD = "backward"  # Referenced works
    AUTHOR = "author"
    RELATED = "related"


class DownloadStatus(str, Enum):
    """PDF download status."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class IterationMode(str, Enum):
    """Snowball iteration control mode."""

    AUTOMATIC = "automatic"
    SEMI_AUTOMATIC = "semi-automatic"
    MANUAL = "manual"
    FIXED = "fixed"


# ============================================================================
# OpenAlex API Response Models
# ============================================================================


class YearCount(BaseModel):
    """Citation count for a specific year."""

    year: int
    cited_by_count: int


class OpenAccessInfo(BaseModel):
    """Open access information."""

    is_oa: bool = False
    oa_status: str | None = None
    oa_url: str | None = None


class Location(BaseModel):
    """Publication location (journal, repository, etc.)."""

    is_oa: bool = False
    landing_page_url: str | None = None
    pdf_url: str | None = None
    source: dict[str, Any] | None = None
    license: str | None = None
    version: str | None = None


class WorkIds(BaseModel):
    """Various identifiers for a work."""

    openalex: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    mag: str | None = None


class AuthorInfo(BaseModel):
    """Author information from OpenAlex."""

    id: str
    display_name: str
    orcid: str | None = None


class Authorship(BaseModel):
    """Authorship information for a work."""

    author: AuthorInfo
    author_position: str | None = None
    is_corresponding: bool = False
    raw_affiliation_strings: list[str] = Field(default_factory=list)
    institutions: list[dict[str, Any]] = Field(default_factory=list)


class Work(BaseModel):
    """OpenAlex Work object (partial, fields we need)."""

    id: str  # OpenAlex ID, e.g., "https://openalex.org/W2741809807"
    doi: str | None = None
    title: str | None = Field(None, alias="display_name")
    publication_year: int | None = None
    publication_date: str | None = None
    type: str | None = None  # journal-article, review, posted-content, etc.
    language: str | None = None
    is_retracted: bool = False

    # Citations
    cited_by_count: int = 0
    counts_by_year: list[YearCount] = Field(default_factory=list)
    referenced_works: list[str] = Field(default_factory=list)  # OpenAlex IDs
    related_works: list[str] = Field(default_factory=list)

    # Authors
    authorships: list[Authorship] = Field(default_factory=list)

    # Content availability
    has_fulltext: bool = False

    # Identifiers
    ids: WorkIds | None = None

    # Abstract (inverted index format)
    abstract_inverted_index: dict[str, list[int]] | None = None

    # Open Access
    open_access: OpenAccessInfo | None = None
    best_oa_location: Location | None = None

    class Config:
        populate_by_name = True

    @property
    def openalex_id(self) -> str:
        """Extract short OpenAlex ID (e.g., W2741809807)."""
        return self.id.replace("https://openalex.org/", "")

    @property
    def author_ids(self) -> list[str]:
        """Get list of author OpenAlex IDs."""
        return [a.author.id for a in self.authorships]

    @property
    def abstract(self) -> str | None:
        """Reconstruct abstract from inverted index."""
        if not self.abstract_inverted_index:
            return None

        # Reconstruct text from inverted index
        positions: list[tuple[int, str]] = []
        for word, indices in self.abstract_inverted_index.items():
            for idx in indices:
                positions.append((idx, word))

        positions.sort(key=lambda x: x[0])
        return " ".join(word for _, word in positions)


class Meta(BaseModel):
    """Pagination metadata from OpenAlex API."""

    count: int
    db_response_time_ms: int | None = None
    page: int | None = None
    per_page: int | None = None


class WorksResponse(BaseModel):
    """Paginated response from OpenAlex /works endpoint."""

    meta: Meta
    results: list[Work]
    next_cursor: str | None = None


# ============================================================================
# Application Models
# ============================================================================


class ScoreBreakdown(BaseModel):
    """Breakdown of paper scoring components."""

    citation_velocity: float = 0.0
    recent_citations: float = 0.0
    foundational_score: float = 0.0
    author_overlap: float = 0.0
    recency_bonus: float = 0.0
    total: float = 0.0


class ScoringWeights(BaseModel):
    """Weights for scoring algorithm."""

    citation_velocity: float = 0.25
    recent_citations: float = 0.20
    foundational: float = 0.25
    author_overlap: float = 0.15
    recency: float = 0.15


class Paper(BaseModel):
    """Paper entity with discovery metadata."""

    # Core identifiers
    id: str  # Internal UUID
    openalex_id: str
    doi: str | None = None
    pmid: str | None = None

    # Metadata
    title: str
    authors: list[AuthorInfo] = Field(default_factory=list)
    publication_year: int | None = None
    journal: str | None = None
    abstract: str | None = None
    language: str | None = None
    type: str | None = None

    # Citation data
    cited_by_count: int = 0
    counts_by_year: list[YearCount] = Field(default_factory=list)
    referenced_works: list[str] = Field(default_factory=list)

    # Discovery metadata
    score: float = 0.0
    score_components: ScoreBreakdown | None = None
    discovery_method: DiscoveryMethod = DiscoveryMethod.SEED
    discovered_from: list[str] = Field(default_factory=list)  # Paper IDs
    iteration_added: int = 0

    # Download status
    download_status: DownloadStatus = DownloadStatus.PENDING
    local_path: Path | None = None
    oa_url: str | None = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)


class IterationMetrics(BaseModel):
    """Metrics for a single snowball iteration."""

    iteration_number: int
    timestamp: datetime = Field(default_factory=datetime.now)
    papers_before: int
    papers_after: int
    new_papers: int
    growth_rate: float  # new_papers / papers_before
    novelty_rate: float  # new_papers / total_candidates
    forward_found: int = 0
    backward_found: int = 0
    author_found: int = 0
    related_found: int = 0


class ProjectConfig(BaseModel):
    """User-configurable project settings."""

    # Scoring weights
    weights: ScoringWeights = Field(default_factory=ScoringWeights)

    # Filtering
    min_year: int | None = None
    max_year: int | None = None
    min_citations: int = 0
    include_preprints: bool = True
    language: str = "en"

    # Iteration control
    iteration_mode: IterationMode = IterationMode.SEMI_AUTOMATIC
    max_iterations: int = 5
    max_papers: int = 500
    papers_per_iteration: int = 50
    growth_threshold: float = 0.05
    novelty_threshold: float = 0.10

    # Download settings
    download_directory: str = "downloads"
    user_email: str = ""


class Project(BaseModel):
    """Project container."""

    id: str
    name: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    config: ProjectConfig = Field(default_factory=ProjectConfig)

    # State tracking
    current_iteration: int = 0
    is_complete: bool = False


class DownloadResult(BaseModel):
    """Result of a PDF download attempt."""

    paper_id: str
    openalex_id: str
    success: bool
    file_path: Path | None = None
    error_message: str | None = None
    credits_used: int = 0  # OpenAlex content API credits
