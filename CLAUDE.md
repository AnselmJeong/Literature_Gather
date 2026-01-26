# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Citation Snowball** is a Python CLI application that helps biomedical researchers discover related literature through bidirectional citation analysis. Starting from seed articles (PDFs), it uses snowball sampling to find foundational papers (backward citations) and recent developments (forward citations), with automatic saturation detection to determine when to stop.

## Implementation Status

### ✅ Completed Features (v1.0)

| Component | Status | Location |
|-----------|--------|----------|
| **Project Structure** | ✅ Complete | `src/citation_snowball/` package layout |
| **Data Models** | ✅ Complete | `core/models.py` - Pydantic models for Work, Paper, Project, etc. |
| **Database Layer** | ✅ Complete | `db/schema.sql`, `db/database.py`, `db/repository.py` |
| **Configuration** | ✅ Complete | `config.py` - pydantic-settings based |
| **OpenAlex API Client** | ✅ Complete | `services/openalex.py` - Rate limiting, caching, batch ops |
| **Unpaywall API Client** | ✅ Complete | `services/unpaywall.py` - OA PDF download |
| **Crossref API Client** | ✅ Complete | `services/crossref.py` - DOI lookup fallback |
| **PDF Parser** | ✅ Complete | `services/pdf_parser.py` - DOI, title, author, PMID extraction |
| **Scoring Algorithm** | ✅ Complete | `snowball/scoring.py` - 5-component scoring |
| **Saturation Detection** | ✅ Complete | `snowball/saturation.py` - Multi-condition termination |
| **Paper Filter** | ✅ Complete | `snowball/filtering.py` - Inclusion/exclusion filters |
| **Snowball Engine** | ✅ Complete | `snowball/engine.py` - Main iteration logic |
| **PDF Downloader** | ✅ Complete | `services/downloader.py` - Concurrent downloads |
| **HTML Report Generator** | ✅ Complete | `export/html_report.py` - Download/collection reports |
| **CLI Application** | ✅ Complete | `cli/app.py` - 8 commands with rich UI |
| **Tests** | ✅ Complete | `tests/` - 13 tests (all passing) |

### CLI Commands

```bash
# Project Management
uv run snowball init <name>              # Create new project
uv run snowball list                    # List all projects
uv run snowball delete <project>        # Delete project

# Seed Import
uv run snowball import-seeds <folder>   # Import PDFs as seed papers

# Snowballing
uv run snowball snowball <project>      # Run snowballing process

# Results & Export
uv run snowball results <project>       # Show collected papers
uv run snowball download <project>      # Download PDFs
uv run snowball export <project>        # Export to HTML/CSV
```

## Technology Stack

- **Language**: Python 3.12+
- **CLI Framework**: `rich` for terminal UI, `typer` for command parsing
- **Database**: SQLite for local storage
- **HTTP Client**: `httpx` (async)
- **PDF Parsing**: `pypdf`
- **Async**: `asyncio` for concurrent API calls
- **Testing**: `pytest`, `pytest-asyncio`, `pytest-cov`

## Development Commands

```bash
# Install dependencies (use uv for package management)
uv add --dev pytest pytest-cov pytest-asyncio

# Run the CLI
uv run snowball --help
uv run snowball list

# Testing
uv run pytest tests/ -v                 # Run all tests
uv run pytest tests/test_scoring.py -v  # Run specific test file

# Type checking (if mypy installed)
uv run mypy src/

# Linting (if ruff installed)
uv run ruff check .
uv run ruff format .
```

## External APIs

| API | Purpose | Rate Limiting |
|-----|---------|---------------|
| OpenAlex | Citation data, paper metadata, author works | 10 req/sec (polite pool with email) |
| Unpaywall | Open access PDF URLs | 10 req/sec |
| CrossRef | DOI lookup fallback from titles | As needed |

## Core Architecture

### Data Flow
1. **Seed Import**: Scan PDF folder → Extract DOI/metadata → Resolve to OpenAlex Work IDs
2. **Snowballing**: For each iteration, collect forward citations, backward citations, and author papers → Score and rank → Select top N → Check saturation
3. **Results**: Download available OA PDFs via Unpaywall → Generate HTML report for unavailable papers

### Scoring Algorithm
Papers are scored using a weighted combination of:
- Citation velocity (citations/age)
- Recent citations (last 3 years)
- Foundational score (how many seeds cite this paper)
- Author overlap with seeds
- Recency bonus

Default weights: velocity=0.25, recent=0.20, foundational=0.25, author=0.15, recency=0.15

### Saturation Detection
Stop when any condition is met (checked in order):
1. No new papers added
2. Maximum iterations reached (default: 5)
3. Growth rate < threshold (default: 5%)
4. Novelty rate < threshold (default: 10%)

## Key OpenAlex Endpoints

```
GET /works/{id}                      # Single work with referenced_works field
GET /works?filter=cites:{id}         # Forward citations
GET /works?filter=author.id:{id}     # Author's publications
GET /works?filter=doi:{doi}          # Lookup by DOI
GET /works?search={title}            # Title search
```

Use `mailto={email}` parameter for polite pool access. Batch up to 50 IDs with pipe separator: `filter=openalex_id:W1|W2|W3`

## Database Schema

Main tables: `projects`, `papers`, `iterations`, `api_cache`

Papers track: OpenAlex ID, DOI, PMID, metadata, score components, discovery method (seed/forward/backward/author), iteration added, download status.

## DOI Extraction

Regex pattern for PDFs: `10.\d{4,9}/[-._;()/:A-Z0-9]+`

## Project Structure

```
src/citation_snowball/
├── __init__.py
├── __main__.py
├── config.py                 # Application configuration
├── cli/
│   └── app.py                # Typer CLI application
├── core/
│   └── models.py             # Pydantic models
├── db/
│   ├── schema.sql            # Database schema
│   ├── database.py           # Database connection
│   └── repository.py         # Repository layer
├── services/
│   ├── openalex.py           # OpenAlex API client
│   ├── unpaywall.py          # Unpaywall API client
│   ├── crossref.py           # Crossref API client
│   ├── pdf_parser.py         # PDF metadata extraction
│   └── downloader.py         # PDF download service
├── snowball/
│   ├── engine.py             # Snowballing engine
│   ├── scoring.py            # Scoring algorithm
│   ├── saturation.py         # Saturation detection
│   └── filtering.py          # Paper filters
└── export/
    └── html_report.py        # HTML report generator
```

## Environment Variables

Create `.env` file in project root:

```env
OPENALEX_API_KEY=your@email.com
# Other optional settings can go here
```

## Testing

Test files are located in `tests/`:
- `tests/test_scoring.py` - Scoring algorithm tests
- `tests/test_saturation.py` - Saturation detection tests

All tests use pytest and can be run with `uv run pytest tests/ -v`.