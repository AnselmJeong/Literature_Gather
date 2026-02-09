from __future__ import annotations

import re

from ref_counter.models import CitationStyle


class CitationStyleUndetectable(RuntimeError):
    pass


def detect_style(body_text: str) -> CitationStyle:
    patterns: dict[CitationStyle, str] = {
        CitationStyle.NUMBERED_BRACKET: r"\[\d+(?:[\s,]*\d+)*(?:\s*[-–]\s*\d+)?\]",
        CitationStyle.NUMBERED_SUPERSCRIPT: r"[\u00B9\u00B2\u00B3\u2070-\u2079]+",
        CitationStyle.AUTHOR_YEAR: r"\([A-Z][A-Za-z\-']+(?:\s+et\s+al\.?|\s*&\s*[A-Z][A-Za-z\-']+)?,?\s*\d{4}[a-z]?",
    }
    counts = {style: len(re.findall(pat, body_text)) for style, pat in patterns.items()}
    best = max(counts, key=counts.get)
    if counts[best] < 5:
        raise CitationStyleUndetectable(f"No clear style found: {counts}")
    return best
