from __future__ import annotations

import asyncio
from pathlib import Path

from ref_counter.extract.paper_identity import identify_pdf
from ref_counter.extract.pdf_reader import extract_text_blocks
from ref_counter.extract.section_split import split_body_and_references
from ref_counter.models import CitationStyle, PaperResult, RefFrequency
from ref_counter.parse.author_year import aggregate_author_year, parse_author_year_citations
from ref_counter.parse.numbered import aggregate_numbered, parse_bracket_citations, parse_superscript_citations
from ref_counter.parse.reflist import parse_reference_list
from ref_counter.parse.style_detect import CitationStyleUndetectable, detect_style


def run_pipeline(
    input_dir: str | Path,
    *,
    api_key: str | None,
    no_resolve: bool,
    min_freq: int,
    weighted: bool,
    force_style: CitationStyle | None,
    concurrency: int,
    verbose: bool,
) -> dict:
    return asyncio.run(
        _run_pipeline_async(
            Path(input_dir),
            api_key=api_key,
            no_resolve=no_resolve,
            min_freq=min_freq,
            weighted=weighted,
            force_style=force_style,
            concurrency=concurrency,
            verbose=verbose,
        )
    )


async def _run_pipeline_async(
    input_dir: Path,
    *,
    api_key: str | None,
    no_resolve: bool,
    min_freq: int,
    weighted: bool,
    force_style: CitationStyle | None,
    concurrency: int,
    verbose: bool,
) -> dict:
    from ref_counter.output import aggregate_results

    pdfs = sorted(input_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDF files found in {input_dir}")

    per_paper: list[PaperResult] = []

    if no_resolve:
        for p in pdfs:
            per_paper.append(_process_one_no_resolve(p, min_freq=min_freq, weighted=weighted, force_style=force_style, verbose=verbose))
        return aggregate_results(per_paper, input_dir)

    if not api_key:
        raise ValueError("OpenAlex API key is required. Set --api-key or OPENALEX_API_KEY")

    from ref_counter.resolve.openalex import OpenAlexClient

    async with OpenAlexClient(api_key=api_key, concurrency=concurrency) as client:
        for p in pdfs:
            per_paper.append(
                await _process_one_with_resolve(
                    p,
                    client=client,
                    min_freq=min_freq,
                    weighted=weighted,
                    force_style=force_style,
                    verbose=verbose,
                )
            )

    return aggregate_results(per_paper, input_dir)


def _process_one_no_resolve(
    pdf_path: Path,
    *,
    min_freq: int,
    weighted: bool,
    force_style: CitationStyle | None,
    verbose: bool,
) -> PaperResult:
    if verbose:
        print(f"[ref_counter] processing {pdf_path}")
    blocks = extract_text_blocks(pdf_path)
    if not blocks:
        return PaperResult(source_pdf=pdf_path.name, source_openalex_id=None, source_doi=None, citation_style="unknown", total_references=0, references_resolved=0, errors=["No text layer detected"])

    split = split_body_and_references(blocks)
    style = force_style or _detect_style_fallback(split.body_text, blocks)
    refs = parse_reference_list(split.reference_text, style)
    frequencies = _compute_frequencies(style, split.body_text, blocks, refs, weighted)
    frequencies = [f for f in frequencies if f.in_text_count >= min_freq]

    return PaperResult(
        source_pdf=pdf_path.name,
        source_openalex_id=None,
        source_doi=None,
        citation_style=style.value,
        total_references=len(refs),
        references_resolved=0,
        references=frequencies,
    )


async def _process_one_with_resolve(
    pdf_path: Path,
    *,
    client,
    min_freq: int,
    weighted: bool,
    force_style: CitationStyle | None,
    verbose: bool,
) -> PaperResult:
    base = _process_one_no_resolve(pdf_path, min_freq=min_freq, weighted=weighted, force_style=force_style, verbose=verbose)

    ident = identify_pdf(pdf_path)
    seed_oa, seed_doi = await client.identify_seed(ident.doi, ident.title)
    base.source_openalex_id = seed_oa.replace("https://openalex.org/", "") if seed_oa else None
    base.source_doi = seed_doi.replace("https://doi.org/", "") if seed_doi else ident.doi

    resolve_tasks = [client.resolve_ref(r.entry) for r in base.references]
    resolved = await asyncio.gather(*resolve_tasks)
    for item, rs in zip(base.references, resolved):
        item.resolved = rs

    base.references_resolved = sum(1 for r in base.references if r.resolved is not None)

    return base


def _detect_style_fallback(body_text: str, blocks) -> CitationStyle:
    try:
        return detect_style(body_text)
    except CitationStyleUndetectable:
        # fallback trial: choose whichever parser extracts more events
        bracket = len(parse_bracket_citations(body_text))
        supers = len(parse_superscript_citations(blocks))
        author = len(parse_author_year_citations(body_text))
        if max(bracket, supers, author) == author:
            return CitationStyle.AUTHOR_YEAR
        if max(bracket, supers, author) == supers:
            return CitationStyle.NUMBERED_SUPERSCRIPT
        return CitationStyle.NUMBERED_BRACKET


def _compute_frequencies(
    style: CitationStyle,
    body_text: str,
    blocks,
    refs,
    weighted: bool,
) -> list[RefFrequency]:
    out: list[RefFrequency] = []
    if style in (CitationStyle.NUMBERED_BRACKET, CitationStyle.NUMBERED_SUPERSCRIPT):
        events = parse_bracket_citations(body_text)
        if style == CitationStyle.NUMBERED_SUPERSCRIPT:
            events.extend(parse_superscript_citations(blocks))
        cnt, wcnt = aggregate_numbered(events, weighted=weighted)
        ref_by_num = {r.index: r for r in refs if r.index is not None}
        for num, c in sorted(cnt.items(), key=lambda x: x[1], reverse=True):
            entry = ref_by_num.get(num)
            if not entry:
                continue
            out.append(
                RefFrequency(
                    ref_number=num,
                    key=str(num),
                    in_text_count=c,
                    weighted_count=wcnt.get(num, float(c)),
                    entry=entry,
                )
            )
        return out

    citations = parse_author_year_citations(body_text)
    cnt, wcnt = aggregate_author_year(citations)
    for key, c in sorted(cnt.items(), key=lambda x: x[1], reverse=True):
        author, _, year = key.rpartition("_")
        entry = _best_ref_for_author_year(refs, author, year)
        if not entry:
            continue
        out.append(
            RefFrequency(
                ref_number=entry.index,
                key=key,
                in_text_count=c,
                weighted_count=wcnt.get(key, float(c)),
                entry=entry,
            )
        )
    return out


def _best_ref_for_author_year(refs, author: str, year: str):
    author_l = author.lower()
    for r in refs:
        if r.year and str(r.year) != str(year)[:4]:
            continue
        if author_l.split()[0] in r.authors.lower():
            return r
    return None
