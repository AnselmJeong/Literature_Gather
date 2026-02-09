from __future__ import annotations

import re
import statistics

from ref_counter.models import SplitResult, TextBlock

REFERENCE_HEADERS = [
    r"^references?\s*$",
    r"^bibliography\s*$",
    r"^works?\s+cited\s*$",
    r"^literature\s+cited\s*$",
    r"^참고\s*문헌\s*$",
]

SUPPLEMENTARY_HEADERS = [
    r"^supplementary",
    r"^appendix",
    r"^supporting\s+information",
]


def split_body_and_references(blocks: list[TextBlock]) -> SplitResult:
    if not blocks:
        return SplitResult(body_text="", reference_text="", ref_start_page=None)

    blocks_sorted = sorted(blocks, key=lambda b: (b.page, b.bbox[1], b.bbox[0]))
    pages = max(b.page for b in blocks_sorted) + 1
    sizes = [b.font_size for b in blocks_sorted if b.font_size > 0]
    med_size = statistics.median(sizes) if sizes else 10.0

    start_idx = _find_header_boundary(blocks_sorted, pages, med_size)
    if start_idx is None:
        start_idx = _find_pattern_boundary(blocks_sorted)
    if start_idx is None:
        start_idx = int(len(blocks_sorted) * 0.8)

    end_idx = _find_supp_boundary(blocks_sorted, start_idx)
    body = "\n".join(b.text for b in blocks_sorted[:start_idx]).strip()
    refs = "\n".join(b.text for b in blocks_sorted[start_idx:end_idx]).strip()
    page = blocks_sorted[start_idx].page if blocks_sorted[start_idx:] else None
    return SplitResult(body_text=body, reference_text=refs, ref_start_page=page)


def _find_header_boundary(blocks: list[TextBlock], pages: int, med_size: float) -> int | None:
    last_segment_page = int(pages * 0.65)
    for i in range(len(blocks) - 1, -1, -1):
        b = blocks[i]
        t = b.text.strip().lower()
        if b.page < last_segment_page:
            continue
        if not any(re.match(p, t, flags=re.IGNORECASE) for p in REFERENCE_HEADERS):
            continue
        is_headerish = b.font_size >= med_size * 1.15 or ("bold" in b.font_name.lower())
        if is_headerish:
            return i + 1
    return None


def _find_pattern_boundary(blocks: list[TextBlock]) -> int | None:
    # look for dense numbered reference starts in latter part
    start_scan = int(len(blocks) * 0.6)
    streak = 0
    for i in range(start_scan, len(blocks)):
        if re.match(r"^\[?\d{1,3}\]?\.?$", blocks[i].text):
            streak += 1
            if streak >= 5:
                return max(0, i - 4)
        else:
            streak = 0
    return None


def _find_supp_boundary(blocks: list[TextBlock], start_idx: int) -> int:
    for i in range(start_idx, len(blocks)):
        txt = blocks[i].text.strip().lower()
        if any(re.match(p, txt, flags=re.IGNORECASE) for p in SUPPLEMENTARY_HEADERS):
            return i
    return len(blocks)
