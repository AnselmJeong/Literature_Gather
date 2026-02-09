## Filename Format

```
[YYYY] - [AUTHORS] - [TITLE]; [SUBTITLE] .pdf
```

### Author Rules

- 1 author: `Smith`
- 2 authors: `Smith, Johnson`
- 3+ authors: `Smith et al.`

### Title Rules

- Colons (`:`) → Semicolons (`;`)
- Subtitle appears after semicolon

### Examples

| Original File | Standardized Filename |
|--------------|----------------------|
| `paper1.pdf` | `2024 - Smith - Neural mechanisms of depression.pdf` |
| `art23.pdf` | `2023 - Smith, Johnson - Treatment resistant depression.pdf` |
| `complex.pdf` | `2024 - Smith et al. - Neural plasticity; A systematic review.pdf` |

---

## PDF Downloader CLI

Download PDFs from OpenAlex given a list of OpenAlex IDs or DOIs. Files are automatically renamed according to the filename format above.

### Prerequisites

- Python 3.12+
- `uv` for dependency management
- OpenAlex API key (optional, for higher success rate via Content API)

### Setup

```bash
# Install dependencies
uv sync

# Set API key (optional but recommended)
export OPENALEX_API_KEY="your_api_key_here"
```

### Usage

```bash
# Basic usage
uv run pdf_downloader input.txt

# Specify output directory
uv run pdf_downloader input.txt -o ./my_papers

# Adjust delay between requests (default: 0.5s)
uv run pdf_downloader input.txt --delay 1.0

# Skip existing files (default: true)
uv run pdf_downloader input.txt --skip-existing
```

### Input File Format

Create a text file with one OpenAlex ID or DOI per line:

```
W2741809807
W4235123456
10.7717/peerj.4375
https://doi.org/10.7717/peerj.4375
https://openalex.org/W2741809807
```

### Output

Downloaded PDFs are saved to `./downloads/` (or specified output directory) with standardized filenames.

### Download Sources

The CLI attempts to download PDFs from multiple sources in order:

1. **OpenAlex Content API** (if `OPENALEX_API_KEY` is set) - highest quality PDFs hosted by OpenAlex
2. **best_oa_location.pdf_url** - direct PDF links from publishers or repositories
3. **primary_location.pdf_url** - fallback to primary location PDF
4. **other locations** - checks all available locations for PDF links

If no PDF is available, the CLI will display the landing page URL for manual access.
