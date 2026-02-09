from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from ref_counter.models import CitationStyle
from ref_counter.pipeline import run_pipeline


@click.command()
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None, help="Output JSON file path (default: stdout)")
@click.option("--api-key", default=None, help="OpenAlex API key (or set OPENALEX_API_KEY)")
@click.option("--min-freq", default=2, type=int, show_default=True)
@click.option("--no-resolve", is_flag=True)
@click.option("--weighted/--no-weighted", default=True, show_default=True)
@click.option("--style", "forced_style", type=click.Choice([s.value for s in CitationStyle]), default=None)
@click.option("--concurrency", default=5, type=int, show_default=True)
@click.option("--verbose", is_flag=True)
@click.option("--quiet", is_flag=True)
def main(
    input_dir: Path,
    output: Path | None,
    api_key: str | None,
    min_freq: int,
    no_resolve: bool,
    weighted: bool,
    forced_style: str | None,
    concurrency: int,
    verbose: bool,
    quiet: bool,
):
    """Analyze in-text citation frequency from PDF papers."""
    try:
        _load_dotenv(input_dir.parent)
        _load_dotenv(Path.cwd())
        effective_key = api_key or os.getenv("OPENALEX_API_KEY")
        style_enum = CitationStyle(forced_style) if forced_style else None

        data = run_pipeline(
            input_dir,
            api_key=effective_key,
            no_resolve=no_resolve,
            min_freq=min_freq,
            weighted=weighted,
            force_style=style_enum,
            concurrency=concurrency,
            verbose=(verbose and not quiet),
        )

        payload = json.dumps(data, ensure_ascii=False, indent=2)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload, encoding="utf-8")
            if not quiet:
                click.echo(f"Wrote results to {output}", err=True)
        else:
            click.echo(payload)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ref_counter error: {exc}", err=True)
        sys.exit(1)


def _load_dotenv(base_dir: Path) -> None:
    env_path = base_dir / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'\"")


if __name__ == "__main__":
    main()
