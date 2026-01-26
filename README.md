# Citation Snowball

Citation Snowball is a Python CLI application that helps biomedical researchers discover related literature through bidirectional citation analysis. Starting from seed articles (PDFs), it uses snowball sampling to find foundational papers (backward citations) and recent developments (forward citations), with automatic saturation detection to determine when to stop.

## Features

- **Simple Directory-Based Projects**: Each PDF folder is its own project
- **One-Command Workflow**: `snowball run` does everything automatically
- **Seed Import**: Import PDFs and automatically extract DOIs and metadata
- **Bidirectional Snowballing**: Find both backward and forward citations
- **Author Expansion**: Discover other works by seed authors
- **Intelligent Scoring**: Rank papers using a 5-component scoring algorithm
- **Saturation Detection**: Automatically stop when the search is saturated
- **PDF Download**: Download open access PDFs via Unpaywall
- **Export Reports**: Generate HTML and CSV reports

## Installation

### Prerequisites

- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) package manager

### Setup

```bash
# Clone the repository
git clone <repository-url>
cd Literature_Gather

# Install dependencies
uv install
```

### Configuration

Create a `.env` file in the project root:

```env
OPENALEX_API_KEY=your@email.com
```

The `OPENALEX_API_KEY` is actually your email address, which is required for polite pool access to the OpenAlex API.

## Usage

### Quick Start

```bash
# Navigate to your PDF directory
cd /path/to/your/papers

# Run snowballing - one command does everything
uv run snowball run
```

That's it! The `run` command will:
1. Create a `.snowball/` directory for project data
2. Import all PDFs in the current directory as seed papers
3. Run the snowballing process to discover related papers
4. Download available open access PDFs
5. Generate an HTML report

### Main Command: `run`

```bash
# Run in current directory
uv run snowball run

# Run in a specific directory
uv run snowball run ./my-papers

# With options
uv run snowball run --max-iterations 3  # Limit iterations
uv run snowball run --mode fixed        # Use fixed iteration mode
uv run snowball run --no-download       # Skip PDF download
uv run snowball run --no-export         # Skip report export
uv run snowball run --resume            # Resume existing project
```

### Other Commands

```bash
# Show collected papers
uv run snowball results
uv run snowball results --sort year --limit 20

# Download PDFs (if skipped during run)
uv run snowball download

# Export reports (if skipped during run)
uv run snowball export

# Show project information
uv run snowball info

# Reset project (delete .snowball/ directory)
uv run snowball reset
```

### Project Structure

Each PDF directory creates its own project:

```
my-papers/                  # Your PDF directory
├── paper1.pdf
├── paper2.pdf
└── .snowball/              # Project data (hidden)
    ├── snowball.db         # SQLite database
    ├── downloads/          # Downloaded PDFs
    ├── reports/            # Generated reports
    └── cache/              # API cache
```

### Command Reference

| Command | Description |
|---------|-------------|
| `snowball run [dir]` | Run full workflow (init + import + snowball + download + export) |
| `snowball results [dir]` | Show collected papers |
| `snowball download [dir]` | Download PDFs |
| `snowball export [dir]` | Export reports |
| `snowball info [dir]` | Show project information |
| `snowball reset [dir]` | Delete project data |

## How Scoring Works

Papers are scored using a weighted combination of 5 components:

| Component | Description | Weight |
|-----------|-------------|--------|
| Citation Velocity | Citations per year (citations / paper age) | 0.25 |
| Recent Citations | Citations in the last 3 years | 0.20 |
| Foundational Score | How many seed papers cite this paper | 0.25 |
| Author Overlap | Authors shared with seed papers | 0.15 |
| Recency Bonus | Bonus for recent papers | 0.15 |

Higher scores indicate more relevant and important papers.

## Saturation Detection

The snowballing process stops when any condition is met (checked in order):

1. **No new papers**: No new papers were added in the current iteration
2. **Max iterations**: Reached the maximum iteration limit (default: 5)
3. **Growth rate threshold**: Growth rate < 5% (fewer than 5% new papers)
4. **Novelty rate threshold**: Novelty rate < 10% (fewer than 10% relevant new papers)

## Development

```bash
# Run tests
uv run pytest tests/ -v

# Run tests with coverage
uv run pytest tests/ --cov=src --cov-report=html

# Type checking
uv run mypy src/

# Linting
uv run ruff check .
uv run ruff format .
```

## API Rate Limits

| API | Rate Limit |
|-----|------------|
| OpenAlex | 10 requests/second |
| Unpaywall | 10 requests/second |
| CrossRef | As needed |

## License

MIT