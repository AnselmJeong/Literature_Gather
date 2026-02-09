from __future__ import annotations

from rapidfuzz import fuzz

from ref_counter.models import RefEntry


def best_match(entry: RefEntry, candidates: list[dict]) -> tuple[dict | None, float]:
    if not candidates:
        return None, 0.0
    best = None
    best_score = 0.0
    for cand in candidates:
        score = _score(entry, cand)
        if score > best_score:
            best = cand
            best_score = score
    return best, best_score


def _score(entry: RefEntry, cand: dict) -> float:
    cdoi = (cand.get("doi") or "").lower().replace("https://doi.org/", "")
    if entry.doi and cdoi and entry.doi.lower() == cdoi:
        return 1.0

    title = (entry.title or "").strip()
    ctitle = (cand.get("display_name") or cand.get("title") or "").strip()
    title_ratio = fuzz.ratio(title, ctitle) / 100.0 if title and ctitle else 0.0

    year_bonus = 0.0
    cyear = cand.get("publication_year")
    if entry.year and cyear:
        if int(cyear) == int(entry.year):
            year_bonus = 0.15
        elif abs(int(cyear) - int(entry.year)) <= 1:
            year_bonus = 0.05

    author_bonus = 0.0
    first_author = (entry.authors.split(",")[0].split()[0] if entry.authors else "").lower()
    auths = cand.get("authorships") or []
    if first_author and auths:
        for a in auths[:3]:
            nm = ((a.get("author") or {}).get("display_name") or "").lower()
            if first_author in nm:
                author_bonus = 0.1
                break

    return min(1.0, title_ratio * 0.8 + year_bonus + author_bonus)
