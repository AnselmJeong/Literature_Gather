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
# Semantic Scholar API Response Models
# ============================================================================


class YearCount(BaseModel):
    """Citation count for a specific year."""

    year: int
    cited_by_count: int = Field(default=0, alias="citedByCount")

    class Config:
        populate_by_name = True


class OpenAccessPdf(BaseModel):
    """Open access PDF information from Semantic Scholar."""

    url: str | None = None
    status: str | None = None


class S2Author(BaseModel):
    """Semantic Scholar Author information."""

    authorId: str | None = None
    name: str | None = None
    url: str | None = None
    affiliations: list[str] = Field(default_factory=list)
    homepage: str | None = None
    paperCount: int | None = None
    citationCount: int | None = None
    hIndex: int | None = None

    @property
    def display_name(self) -> str:
        """Get display name for compatibility."""
        return self.name or ""

    @property
    def id(self) -> str:
        """Get author ID for compatibility."""
        return self.authorId or ""


class PublicationVenue(BaseModel):
    """Publication venue information."""

    id: str | None = None
    name: str | None = None
    type: str | None = None
    url: str | None = None


class Work(BaseModel):
    """Semantic Scholar Paper object.
    
    Replaces the previous OpenAlex Work model with Semantic Scholar fields.
    """

    # Primary identifiers
    paperId: str  # Semantic Scholar ID
    corpusId: int | None = None
    externalIds: dict[str, Any] | None = None  # {"DOI": "...", "PMID": "...", etc.}
    url: str | None = None

    # Core metadata
    title: str | None = None
    abstract: str | None = None
    venue: str | None = None
    publicationVenue: PublicationVenue | None = None
    year: int | None = None
    publicationDate: str | None = None
    publicationTypes: list[str] | None = None

    # Fields of study
    fieldsOfStudy: list[str] | None = None
    s2FieldsOfStudy: list[dict[str, Any]] = Field(default_factory=list)

    # Citation metrics
    referenceCount: int = 0
    citationCount: int = 0
    influentialCitationCount: int = 0

    # Open access
    isOpenAccess: bool = False
    openAccessPdf: OpenAccessPdf | None = None

    # Authors
    authors: list[S2Author] = Field(default_factory=list)

    # Journal info
    journal: dict[str, Any] | None = None

    # Citation styles
    citationStyles: dict[str, str] | None = None

    # OpenAlex compatibility fields
    referenced_works_data: list[str] = Field(default_factory=list, alias="referenced_works")
    counts_by_year_data: list[YearCount] = Field(default_factory=list, alias="counts_by_year")
    type_value: str | None = Field(default=None, alias="type")
    language_value: str | None = Field(default=None, alias="language")
    is_retracted_value: bool = Field(default=False, alias="is_retracted")

    class Config:
        populate_by_name = True

    # Compatibility properties

    @property
    def openalex_id(self) -> str:
        """Get paper ID (compatibility with old code expecting openalex_id)."""
        return self.paperId

    @property
    def id(self) -> str:
        """Get paper ID."""
        return self.paperId

    @property
    def doi(self) -> str | None:
        """Extract DOI from external IDs."""
        if self.externalIds:
            return self.externalIds.get("DOI")
        return None

    @property
    def pmid(self) -> str | None:
        """Extract PMID from external IDs."""
        if self.externalIds:
            return self.externalIds.get("PubMed")
        return None

    @property
    def publication_year(self) -> int | None:
        """Get publication year (compatibility alias)."""
        return self.year

    @property
    def cited_by_count(self) -> int:
        """Get citation count (compatibility alias)."""
        return self.citationCount

    @property
    def author_ids(self) -> list[str]:
        """Get list of author IDs."""
        return [a.authorId for a in self.authors if a.authorId]

    @property
    def authorships(self) -> list["Authorship"]:
        """Create authorship list for compatibility with existing code."""
        return [
            Authorship(
                author=AuthorInfo(
                    id=a.authorId or "",
                    display_name=a.name or "",
                    orcid=None,
                ),
                author_position=None,
                is_corresponding=False,
            )
            for a in self.authors
        ]

    @property
    def referenced_works(self) -> list[str]:
        """Referenced works."""
        return self.referenced_works_data

    @property
    def related_works(self) -> list[str]:
        """Related works - not available in Semantic Scholar."""
        return []

    @property
    def counts_by_year(self) -> list[YearCount]:
        """Citation counts by year."""
        return self.counts_by_year_data

    @property
    def type(self) -> str | None:
        """Get publication type."""
        if self.publicationTypes:
            return self.publicationTypes[0]
        return self.type_value

    @property
    def language(self) -> str | None:
        """Language."""
        return self.language_value

    @property
    def is_retracted(self) -> bool:
        """Retraction status."""
        return self.is_retracted_value

    @property
    def has_fulltext(self) -> bool:
        """Check if fulltext is available."""
        return self.isOpenAccess

    @property
    def best_oa_location(self) -> dict | None:
        """Get best open access location."""
        if self.openAccessPdf:
            return {"pdf_url": self.openAccessPdf.url}
        return None


class AuthorInfo(BaseModel):
    """Author information (compatibility layer)."""

    id: str
    display_name: str
    orcid: str | None = None


class Authorship(BaseModel):
    """Authorship information for a work (compatibility layer)."""

    author: AuthorInfo
    author_position: str | None = None
    is_corresponding: bool = False
    raw_affiliation_strings: list[str] = Field(default_factory=list)
    institutions: list[dict[str, Any]] = Field(default_factory=list)


class Meta(BaseModel):
    """Pagination metadata from Semantic Scholar API."""

    total: int | None = None
    offset: int | None = None
    next: int | None = None


class WorksResponse(BaseModel):
    """Paginated response from Semantic Scholar search/list endpoints."""

    total: int | None = None
    offset: int | None = None
    next: str | int | None = None
    data: list[Work] = Field(default_factory=list)

    @property
    def results(self) -> list[Work]:
        """Get results (compatibility alias for data)."""
        return self.data

    @property
    def meta(self) -> Meta:
        """Get pagination metadata."""
        return Meta(total=self.total, offset=self.offset, next=self.next)

    @property
    def next_cursor(self) -> str | None:
        """Get next cursor for pagination (as offset)."""
        return str(self.next) if self.next is not None else None


class CitationContext(BaseModel):
    """Citation context from Semantic Scholar."""

    contexts: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    isInfluential: bool = False
    citingPaper: Work | None = None
    citedPaper: Work | None = None


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

    @property
    def author_ids(self) -> list[str]:
        """Get list of author OpenAlex IDs."""
        return [a.id for a in self.authors if a.id]


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
    no_recursion: int | None = None
    max_iterations: int = 5
    max_papers: int = 500
    papers_per_iteration: int = 50
    growth_threshold: float = 0.05
    novelty_threshold: float = 0.1  # Only add papers with score > threshold (relative to parent)
    user_email: str | None = None
    include_keywords: list[str] = Field(default_factory=list)  # Filter papers by keywords

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
    candidate_urls: list[str] = Field(default_factory=list)
    debug_info: dict[str, Any] | None = None  # To store Unpaywall JSON or other debug info
    credits_used: int = 0  # OpenAlex content API credits
