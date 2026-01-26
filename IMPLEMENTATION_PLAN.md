# Implementation Plan - Citation Snowball

## Overview
This document outlines the implementation steps to build the Citation Snowball CLI application based on the PRD.

## Current State (Infrastructure Complete)

### ✅ Already Implemented
- **Project structure** with proper Python package layout
- **Pydantic models** for all core entities (Work, Paper, Project, ScoringWeights, etc.)
- **SQLite schema** with proper tables and indexes
- **Repository layer** for all database operations (Project, Paper, Iteration, Cache)
- **Configuration system** via pydantic-settings
- **Build system** with ruff, pytest, mypy

### ❌ Core Functionality Missing
All business logic, API clients, and CLI commands need to be implemented.

---

## Implementation Phases

### Phase 1: API Service Layer (P0)

#### 1.1 OpenAlex API Client
**File**: `src/citation_snowball/services/openalex.py`

```python
class OpenAlexClient:
    """Client for OpenAlex API with rate limiting and caching."""
    async def get_work(self, work_id: str) -> Work
    async def get_citing_works(self, work_id: str, cursor: str = "*") -> WorksResponse
    async def get_author_works(self, author_id: str, from_year: int | None = None) -> WorksResponse
    async def search_by_doi(self, doi: str) -> Work | None
    async def search_by_title(self, title: str) -> WorksResponse
    async def get_works_batch(self, work_ids: list[str]) -> list[Work]
```

**Key features**:
- Rate limiting (10 req/sec for polite pool)
- Caching via CacheRepository
- Exponential backoff on 429
- Pagination with cursor support
- Batch operations (up to 50 IDs)

#### 1.2 Unpaywall API Client
**File**: `src/citation_snowball/services/unpaywall.py`

```python
class UnpaywallClient:
    """Client for Unpaywall API to find open access PDFs."""
    async def check_oa(self, doi: str) -> OAInfo | None
    async def download_pdf(self, pdf_url: str, save_path: Path) -> bool
```

**Key features**:
- Rate limiting (10 req/sec)
- Prefer PDF over landing page
- Retry with backoff
- User-Agent with email

#### 1.3 Crossref API Client (Fallback)
**File**: `src/citation_snowball/services/crossref.py`

```python
class CrossrefClient:
    """Client for Crossref API - fallback for DOI lookup by title."""
    async def search_by_title(self, title: str) -> list[Work]
```

**Key features**:
- Title-based DOI lookup
- Used when PDF metadata extraction fails

---

### Phase 2: PDF Metadata Extraction (P0)

#### 2.1 PDF Parser Service
**File**: `src/citation_snowball/services/pdf_parser.py`

```python
class PDFParser:
    """Extract metadata from PDF files."""
    def extract_from_file(self, pdf_path: Path) -> PDFMetadata
    def extract_doi(self, text: str) -> str | None
    def extract_title(self, text: str) -> str | None
    def extract_authors(self, text: str) -> list[str]
    def extract_pmid(self, text: str) -> str | None
```

**Key features**:
- Try pypdf first, fall back to pdfplumber
- DOI regex: `10.\d{4,9}/[-._;()/:A-Z0-9]+`
- Handle various PDF text extraction challenges
- PMID extraction for biomedical papers

---

### Phase 3: Core Business Logic (P0)

#### 3.1 Scoring Algorithm
**File**: `src/citation_snowball/snowball/scoring.py`

```python
class Scorer:
    """Calculate relevance scores for papers."""
    def calculate_score(self, paper: Work, context: ScoringContext) -> float
    def get_score_breakdown(self, paper: Work, context: ScoringContext) -> ScoreBreakdown

class ScoringContext:
    """Context needed for scoring."""
    seed_papers: list[Paper]
    seed_authors: set[str]
    current_year: int
    weights: ScoringWeights
```

**Score components**:
1. Citation velocity: `cited_by_count / age`
2. Recent citations: sum of last 3 years
3. Foundational score: seeds citing / total seeds
4. Author overlap: shared authors / total authors
5. Recency bonus: max(0, 1 - age/10)

#### 3.2 Saturation Detection
**File**: `src/citation_snowball/snowball/saturation.py`

```python
def check_saturation(metrics: IterationMetrics, config: ProjectConfig) -> SaturationResult

class SaturationResult:
    is_saturated: bool
    reason: str | None
    confidence: float
```

**Stop conditions**:
1. Growth rate < threshold (default 5%)
2. Novelty rate < threshold (default 10%)
3. Max iterations reached
4. Max papers reached

#### 3.3 Snowballing Engine
**File**: `src/citation_snowball/snowball/engine.py`

```python
class SnowballEngine:
    """Main snowballing iteration engine."""
    def __init__(self, db: Database, api_client: OpenAlexClient, scorer: Scorer)
    async def run(self, project: Project) -> IterationResult
    async def run_iteration(self, project: Project, iteration_num: int) -> IterationMetrics
```

**Iteration workflow**:
1. Get working set (papers from last iteration or seeds)
2. For each paper: fetch forward, backward, author papers
3. Aggregate and deduplicate candidates
4. Filter by criteria (year, type, language, retracted)
5. Score all candidates
6. Select top N not in collection
7. Calculate metrics (growth, novelty)
8. Check saturation
9. Store results

#### 3.4 Paper Filtering
**File**: `src/citation_snowball/snowball/filtering.py`

```python
class PaperFilter:
    """Filter candidate papers based on criteria."""
    def should_include(self, paper: Work, config: ProjectConfig) -> bool
    def should_exclude(self, paper: Work, existing_ids: set[str], config: ProjectConfig) -> bool
```

**Inclusion filters**:
- Publication year range
- Document type (article, review, preprint)
- Language
- Minimum citations

**Exclusion filters**:
- Already in collection
- Retracted papers

---

### Phase 4: PDF Download & Export (P1)

#### 4.1 PDF Download Service
**File**: `src/citation_snowball/services/downloader.py`

```python
class PDFDownloader:
    """Download PDFs using Unpaywall."""
    def __init__(self, unpaywall: UnpaywallClient, db: Database)
    async def download_paper(self, paper: Paper, output_dir: Path) -> DownloadResult
    async def download_batch(self, papers: list[Paper], output_dir: Path) -> list[DownloadResult]
```

**Filename format**: `{year}_{first_author}_{title_short}.pdf`

#### 4.2 HTML Report Generator
**File**: `src/citation_snowball/export/html_report.py`

```python
class HTMLReportGenerator:
    """Generate HTML report for papers."""
    def generate_download_report(self, results: list[DownloadResult], output_path: Path) -> None
    def generate_collection_report(self, project: Project, output_path: Path) -> None
```

**Report sections**:
- Summary statistics
- Papers requiring manual download (links to DOI, Publisher, Google Scholar)
- Successfully downloaded papers
- Sortable/filterable table

---

### Phase 5: CLI Application (P0)

#### 5.1 Main CLI Structure
**File**: `src/citation_snowball/cli/app.py`

```python
app = typer.Typer()

@app.command()
def init(name: str, base_path: Path = Path.cwd()): ...

@app.command()
def import_seeds(folder: Path, project: str = None): ...

@app.command()
def snowball(project: str, config_file: Path = None): ...

@app.command()
def results(project: str, sort: str = "score", limit: int = 100): ...

@app.command()
def download(project: str, output: Path = None, select: str = "all"): ...

@app.command()
def export(project: str, format: str = "html", output: Path = None): ...

@app.command()
def list_projects(): ...

@app.command()
def delete_project(project: str): ...
```

#### 5.2 UI Components (rich)
**File**: `src/citation_snowball/cli/ui.py`

```python
def display_paper_table(papers: list[Paper], sort_by: str = "score")
def display_paper_detail(paper: Paper)
def display_progress(iteration: int, total: int, metrics: IterationMetrics)
def display_saturation_check(result: SaturationResult)
def prompt_continue_saturation() -> bool
def prompt_doi_manual(title: str) -> str | None
```

---

### Phase 6: Project Management (P1)

#### 6.1 Project Commands
**File**: `src/citation_snowball/cli/project.py`

```python
class ProjectManager:
    """Manage project lifecycle."""
    def create(self, name: str, config: ProjectConfig) -> Project
    def load(self, name_or_id: str) -> Project
    def delete(self, project_id: str) -> None
    def list(self) -> list[Project]
```

#### 6.2 Seed Import
**File**: `src/citation_snowball/cli/seed_import.py`

```python
class SeedImporter:
    """Import seed papers from PDF folder."""
    async def import_from_folder(
        self,
        folder: Path,
        project: Project,
        api_client: OpenAlexClient
    ) -> ImportResult
```

**Workflow**:
1. Scan folder for PDFs
2. Extract metadata from each PDF
3. Resolve to OpenAlex works
4. Handle failures (prompt for manual input)
5. Store as seed papers

---

### Phase 7: Testing (P2)

#### 7.1 Test Structure
```
tests/
├── conftest.py                    # Pytest fixtures
├── test_openalex_client.py
├── test_unpaywall_client.py
├── test_pdf_parser.py
├── test_scoring.py
├── test_saturation.py
├── test_snowball_engine.py
├── test_repositories.py
└── test_cli.py
```

#### 7.2 Key Fixtures
```python
@pytest.fixture
def mock_openalex_response(): ...
@pytest.fixture
def mock_db(): ...
@pytest.fixture
def sample_project(): ...
```

---

## Implementation Order

### Sprint 1: Foundation APIs (Core Data Sources)
1. OpenAlex API Client
2. CacheRepository integration
3. OpenAlex client tests

### Sprint 2: Seed Import
4. PDF Parser Service
5. Unpaywall API Client
6. Crossref API Client (fallback)
7. Seed Import CLI command

### Sprint 3: Scoring & Filtering
8. Scoring Algorithm
9. Paper Filters
10. Scoring tests

### Sprint 4: Snowballing Engine
11. Saturation Detection
12. Snowball Engine
13. Iteration workflow
14. Snowball tests

### Sprint 5: CLI & Results
15. Main CLI app structure
16. Project management commands
17. Results display
18. Snowball command with rich UI

### Sprint 6: Download & Export
19. PDF Download Service
20. HTML Report Generator
21. Download command
22. Export command

### Sprint 7: Testing & Polish
23. Add missing tests
24. Error handling improvements
25. Documentation updates
26. Performance optimization

---

## File Structure After Implementation

```
src/citation_snowball/
├── __init__.py
├── __main__.py
├── config.py
├── cli/
│   ├── __init__.py
│   ├── app.py              # Main typer app
│   ├── ui.py               # Rich UI components
│   ├── project.py          # Project management
│   └── seed_import.py      # Seed import workflow
├── core/
│   ├── __init__.py
│   └── models.py           # Pydantic models
├── db/
│   ├── __init__.py
│   ├── schema.sql
│   ├── database.py
│   └── repository.py
├── services/
│   ├── __init__.py
│   ├── openalex.py         # OpenAlex API client
│   ├── unpaywall.py        # Unpaywall API client
│   ├── crossref.py         # Crossref API client
│   ├── pdf_parser.py       # PDF metadata extraction
│   └── downloader.py       # PDF download service
├── snowball/
│   ├── __init__.py
│   ├── engine.py           # Main snowballing engine
│   ├── scoring.py          # Scoring algorithm
│   ├── saturation.py       # Saturation detection
│   └── filtering.py        # Paper filters
└── export/
    ├── __init__.py
    └── html_report.py      # HTML report generator
```

---

## Dependencies Already in pyproject.toml
- `rich` - Terminal UI
- `httpx` - Async HTTP client
- `pydantic` / `pydantic-settings` - Data models and settings
- `pypdf` / `pdfplumber` - PDF parsing
- `jinja2` - Template engine
- `typer` - CLI framework
- `tenacity` - Retry logic
- `python-dotenv` - Environment variables

## Next Steps
1. Start with OpenAlex API client (foundational for all features)
2. Implement PDF parser for seed import
3. Build scoring algorithm
4. Assemble snowballing engine
5. Wrap in CLI with rich UI