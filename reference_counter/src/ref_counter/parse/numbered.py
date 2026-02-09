from __future__ import annotations

import re
from collections import Counter

from ref_counter.models import CitationEvent, TextBlock

SUPERSCRIPT_TRANSLATION = str.maketrans({
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
    "⁻": "-",
    "⁽": "(",
    "⁾": ")",
    "，": ",",
    "﹐": ",",
})


def parse_bracket_citations(body_text: str) -> list[CitationEvent]:
    events: list[CitationEvent] = []
    for m in re.finditer(r"\[([\d,\s\-–]+)\]", body_text):
        raw = m.group(0)
        numbers, has_range = expand_citation_range(m.group(1))
        if not numbers:
            continue
        events.append(
            CitationEvent(
                ref_numbers=numbers,
                is_range=has_range,
                range_size=len(numbers),
                raw_text=raw,
            )
        )
    return events


def parse_superscript_citations(blocks: list[TextBlock]) -> list[CitationEvent]:
    events: list[CitationEvent] = []
    for b in blocks:
        if not b.is_superscript and not _contains_superscript_digit(b.text):
            continue
        normalized = b.text.translate(SUPERSCRIPT_TRANSLATION)
        normalized = re.sub(r"[^\d,\-–]", "", normalized)
        if not re.search(r"\d", normalized):
            continue
        numbers, has_range = expand_citation_range(normalized)
        if not numbers:
            continue
        events.append(
            CitationEvent(
                ref_numbers=numbers,
                is_range=has_range,
                range_size=len(numbers),
                raw_text=b.text,
                page=b.page,
            )
        )
    return events


def expand_citation_range(s: str) -> tuple[list[int], bool]:
    nums: list[int] = []
    saw_range = False
    for part in re.split(r"[,\s]+", s.strip()):
        part = part.strip()
        if not part:
            continue
        if "-" in part or "–" in part:
            bits = re.split(r"[-–]", part)
            if len(bits) != 2 or not bits[0].isdigit() or not bits[1].isdigit():
                continue
            start, end = int(bits[0]), int(bits[1])
            if end < start:
                start, end = end, start
            nums.extend(list(range(start, end + 1)))
            saw_range = True
        elif part.isdigit():
            nums.append(int(part))
    return nums, saw_range


def aggregate_numbered(events: list[CitationEvent], weighted: bool = True) -> tuple[dict[int, int], dict[int, float]]:
    count = Counter()
    wcount = Counter()
    for ev in events:
        per = 1.0
        if weighted and ev.is_range and ev.range_size > 1:
            per = 1.0 / ev.range_size
        for n in ev.ref_numbers:
            count[n] += 1
            wcount[n] += per
    return dict(count), dict(wcount)


def _contains_superscript_digit(text: str) -> bool:
    return any(ch in "⁰¹²³⁴⁵⁶⁷⁸⁹" for ch in text)
