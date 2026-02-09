from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ref_counter.models import PaperResult, RefFrequency


def ref_to_dict(r: RefFrequency) -> dict:
    payload = {
        "ref_number": r.ref_number,
        "in_text_count": r.in_text_count,
        "weighted_count": round(r.weighted_count, 4),
        "openalex_id": None,
        "doi": r.entry.doi,
        "title": r.entry.title,
        "authors": _split_authors(r.entry.authors),
        "year": r.entry.year,
        "journal": r.entry.journal,
        "cited_by_count": None,
        "oa_pdf_url": None,
    }
    if r.resolved:
        payload.update(
            {
                "openalex_id": r.resolved.openalex_id,
                "doi": r.resolved.doi or payload["doi"],
                "title": r.resolved.title or payload["title"],
                "authors": r.resolved.authors or payload["authors"],
                "year": r.resolved.year or payload["year"],
                "journal": r.resolved.journal or payload["journal"],
                "cited_by_count": r.resolved.cited_by_count,
                "oa_pdf_url": r.resolved.oa_pdf_url,
                "resolution_confidence": r.resolved.resolution_confidence,
                "resolution_method": r.resolved.resolution_method,
            }
        )
    return payload


def aggregate_results(per_paper: list[PaperResult], input_dir: Path) -> dict:
    grouped: dict[str, dict] = {}
    source_openalex_ids: list[str] = []
    seen_ids: set[str] = set()

    for paper in per_paper:
        if paper.source_openalex_id and paper.source_openalex_id not in seen_ids:
            source_openalex_ids.append(paper.source_openalex_id)
            seen_ids.add(paper.source_openalex_id)

    for paper in per_paper:
        for ref in paper.references:
            if ref.resolved and ref.resolved.openalex_id:
                key = f"oa:{ref.resolved.openalex_id}"
                title = ref.resolved.title
                doi = ref.resolved.doi
                year = ref.resolved.year
            else:
                key = f"raw:{(ref.entry.title or ref.entry.raw_text)[:120].lower()}"
                title = ref.entry.title
                doi = ref.entry.doi
                year = ref.entry.year

            g = grouped.setdefault(
                key,
                {
                    "openalex_id": ref.resolved.openalex_id if ref.resolved else None,
                    "doi": doi,
                    "title": title,
                    "year": year,
                    "total_in_text_mentions": 0,
                    "cited_by_n_seed_papers": 0,
                    "max_mentions_in_single_paper": 0,
                    "seed_papers_citing": [],
                },
            )
            g["total_in_text_mentions"] += ref.in_text_count
            g["max_mentions_in_single_paper"] = max(g["max_mentions_in_single_paper"], ref.in_text_count)
            if paper.source_openalex_id and paper.source_openalex_id not in g["seed_papers_citing"]:
                g["seed_papers_citing"].append(paper.source_openalex_id)
            elif paper.source_pdf not in g["seed_papers_citing"]:
                g["seed_papers_citing"].append(paper.source_pdf)

    for g in grouped.values():
        g["cited_by_n_seed_papers"] = len(g["seed_papers_citing"])
        if g["cited_by_n_seed_papers"]:
            g["avg_mentions_per_paper"] = round(g["total_in_text_mentions"] / g["cited_by_n_seed_papers"], 4)
        else:
            g["avg_mentions_per_paper"] = 0.0

    return {
        "source_openalex_ids": source_openalex_ids,
        "metadata": {
            "input_dir": str(input_dir),
            "pdfs_processed": len(per_paper),
            "pdfs_failed": sum(1 for p in per_paper if p.errors),
            "total_unique_references": len(grouped),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "aggregate_references": sorted(grouped.values(), key=lambda x: x["total_in_text_mentions"], reverse=True),
    }


def _split_authors(authors: str) -> list[str]:
    chunks = [a.strip() for a in authors.replace(" and ", ",").split(",") if a.strip()]
    return chunks[:20]
