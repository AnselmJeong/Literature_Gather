# ref_counter

In-text citation frequency analyzer for academic PDFs.

## Install

```bash
pip install -e .
```

## Usage

```bash
ref_counter ./papers --api-key "$OPENALEX_API_KEY" -o result.json
```

Quick scan without OpenAlex:

```bash
ref_counter ./papers --no-resolve
```

If `.env` contains `OPENALEX_API_KEY=...`, you can omit `--api-key`.
