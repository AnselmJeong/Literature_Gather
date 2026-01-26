# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Citation Snowball** is a Python CLI application that helps biomedical researchers discover related literature through bidirectional citation analysis. Starting from seed articles (PDFs), it uses snowball sampling to find foundational papers (backward citations) and recent developments (forward citations), with automatic saturation detection to determine when to stop.

## Technology Stack

- **Language**: Python
- **CLI Framework**: `rich` for terminal UI, `typer` for command parsing
- **Database**: SQLite for local storage
- **HTTP Client**: `httpx` (async)
- **PDF Parsing**: `pypdf` or `pdfplumber`

## Development Commands

```bash
# Install dependencies
pip install -e .[dev]

# Run the CLI
python -m citation_snowball  # or just `snowball`

# Linting
ruff check .
ruff format .

# Type checking
mypy src/

# Testing
pytest
pytest tests/ -v
pytest tests/test_module.py -v  # Run single test file
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
Stop when any condition is met:
- Growth rate < 5%
- Novelty rate < 10%
- Max iterations reached (default: 5)
- Max papers reached (default: 500)

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