from __future__ import annotations

from pathlib import Path

import fitz
import pdfplumber

from ref_counter.models import TextBlock


def extract_text_blocks(pdf_path: str | Path) -> list[TextBlock]:
    path = Path(pdf_path)
    blocks: list[TextBlock] = []
    try:
        doc = fitz.open(path)
        for page_num, page in enumerate(doc):
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = (span.get("text") or "").strip()
                        if not text:
                            continue
                        flags = int(span.get("flags", 0))
                        blocks.append(
                            TextBlock(
                                text=text,
                                page=page_num,
                                font_size=float(span.get("size", 0.0)),
                                font_name=str(span.get("font", "")),
                                is_superscript=bool(flags & (1 << 0)),
                                bbox=tuple(span.get("bbox", (0.0, 0.0, 0.0, 0.0))),
                            )
                        )
        doc.close()
    except Exception:
        blocks = _fallback_pdfplumber(path)
    return blocks


def _fallback_pdfplumber(path: Path) -> list[TextBlock]:
    out: list[TextBlock] = []
    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            words = page.extract_words(extra_attrs=["fontname", "size"])
            for w in words:
                txt = (w.get("text") or "").strip()
                if not txt:
                    continue
                out.append(
                    TextBlock(
                        text=txt,
                        page=page_num,
                        font_size=float(w.get("size", 0.0)),
                        font_name=str(w.get("fontname", "")),
                        is_superscript=False,
                        bbox=(float(w.get("x0", 0.0)), float(w.get("top", 0.0)), float(w.get("x1", 0.0)), float(w.get("bottom", 0.0))),
                    )
                )
    return out


def extract_plain_text(pdf_path: str | Path) -> str:
    blocks = extract_text_blocks(pdf_path)
    blocks = sorted(blocks, key=lambda b: (b.page, b.bbox[1], b.bbox[0]))
    return "\n".join(b.text for b in blocks)
