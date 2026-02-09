# Citation Snowball

Citation Snowball is a Python CLI for literature expansion from seed PDFs.  
It builds a per-directory project, resolves seed papers to OpenAlex, runs recursive backward/forward expansion, downloads PDFs when available, and exports an HTML report.

## Requirements

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- OpenAlex API key

## Installation

```bash
git clone <repository-url>
cd Literature_Gather
uv sync
```

## Configuration (`.env`)

Create `.env` in the repository root:

```env
OPENALEX_API_KEY=oa_your_real_openalex_api_key
OPENALEX_RATE_LIMIT=10
```

Notes:
- `OPENALEX_API_KEY` must be a real OpenAlex API key (not just email) for content download endpoints.
- Get a key at [openalex.org/users](https://openalex.org/users).

## Core Rule

`run` must be executed first for a directory.

- `snowball expand [directory]` or `snowball run [directory]` creates/updates `.snowball/` project data.
- `results`, `download`, `export`, `info` require an existing project with collected papers.
- If `.snowball` does not exist (or no project data exists), those commands fail with guidance to run `snowball run` first.

## Recommended Workflow (Step-by-step)

```bash
# 1) Move to your PDF folder (or pass it as an argument)
cd /path/to/papers

# 2) Run expansion first (without download/export)
uv run snowball expand . --no-recursion 1

# 3) Inspect discovered papers
uv run snowball results . --sort score --limit 50

# 4) Download PDFs
uv run snowball download .

# 5) Export HTML report
uv run snowball export .

# 6) Check project status
uv run snowball info .
```

## One-command Workflow

```bash
uv run snowball run /path/to/papers
```

This performs import + expansion + download + export in one shot.

## Command Reference

### `expand`

```bash
uv run snowball expand [directory]
```

Expansion-only command:
- imports seed PDFs if needed
- runs recursive citation expansion
- does not download PDFs
- does not export reports

Key options:
- `--max-iterations`, `-n`
- `--no-recursion` (default: `1`)
- `--mode`, `-m`
- `--keywords`, `-k`
- `--resume`, `-r`

### `run`

```bash
uv run snowball run [directory]
```

Key options:
- `--max-iterations`, `-n`: max iteration cap
- `--no-recursion`: number of recursive expansion rounds (default: `1`)
- `--mode`, `-m`: iteration mode (`automatic|semi-automatic|manual|fixed`)
- `--keywords`, `-k`: keyword filters
- `--no-download`: skip download phase
- `--no-export`: skip report export phase
- `--resume`, `-r`: continue existing project

Behavior:
- If directory has no PDFs and no prior seeds, `run` exits with an error.
- On interactive terminals, `run` asks you to confirm `keywords` and `--no-recursion` before execution.
- For `keywords`, you can enter a comma-separated string (for example: `tms, tdcs, neuromodulation`).

### `results`

```bash
uv run snowball results [directory] --sort score --limit 100
```

### `download`

```bash
uv run snowball download [directory]
uv run snowball download [directory] --retry-failed
```

Notes:
- Downloads are attempted for papers without local PDFs.
- Failed downloads generate:
  - `.snowball/reports/download_failed_report.html`
- In the failure report, failed `contents.openalex.org` URLs are hidden.

### `export`

```bash
uv run snowball export [directory]
```

Generates project HTML report under `.snowball/reports/`.

### `info`

```bash
uv run snowball info [directory]
```

Shows project status, counts, config, and file locations.

### `reset`

```bash
uv run snowball reset [directory]
```

Deletes `.snowball/` for that directory after confirmation.

## Project Layout

```text
your-paper-dir/
├── *.pdf
└── .snowball/
    ├── snowball.db
    ├── downloads/
    ├── reports/
    └── cache/
```

## Development

```bash
uv run pytest tests/ -v
uv run mypy src/
uv run ruff check .
```

## License

MIT
