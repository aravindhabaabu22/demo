"""
Turns a flat list of {page_num, blocks:[{text, font_size, is_heading?}]}
into a nested chapter -> pages -> text JSON structure.

Heading detection strategy:
  - A block with an explicit is_heading flag (set by the DOCX extractor from
    Word styles) is trusted as-is.
  - Otherwise, compute the median font size across the document (body text)
    and treat short blocks that are meaningfully larger as headings.
  - Lines that repeat on many pages (running headers/footers, page numbers)
    are removed first so they don't create bogus chapters.
  - Consecutive heading lines ("Chapter 1" / "Introduction") are merged
    into one heading.
  - A heading starts a new chapter; text until the next heading is nested
    under it.
"""

import re
import statistics
from collections import Counter
from typing import Any, Dict, List, Set

PREFACE = "Preface"


def _median_font_size(pages: List[Dict[str, Any]]) -> float:
    sizes = [
        block["font_size"]
        for page in pages
        for block in page.get("blocks", [])
        if block["text"].strip()
    ]
    return statistics.median(sizes) if sizes else 12.0


def _is_heading(block: Dict[str, Any], median_size: float, size_ratio: float = 1.25) -> bool:
    text = block["text"].strip()
    if not text:
        return False
    if "is_heading" in block:
        return bool(block["is_heading"])
    is_large = block["font_size"] >= median_size * size_ratio
    is_short = len(text.split()) <= 12
    return is_large and is_short


def _normalize(text: str) -> str:
    """Lowercase and replace digits so 'Page 12' and 'Page 13' count as the same line."""
    return re.sub(r"\d+", "#", text.strip().lower())


def _repeating_lines(pages: List[Dict[str, Any]], min_pages: int = 6, ratio: float = 0.3) -> Set[str]:
    """Find lines (normalized) that appear on at least `ratio` of pages: headers, footers, page numbers."""
    if len(pages) < min_pages:
        return set()
    counts: Counter = Counter()
    for page in pages:
        seen = {_normalize(b["text"]) for b in page.get("blocks", []) if b["text"].strip()}
        counts.update(seen)
    cutoff = max(3, int(len(pages) * ratio))
    return {line for line, n in counts.items() if n >= cutoff}


def build_structured_json(
    pages: List[Dict[str, Any]],
    title: str = "Untitled Document",
    size_ratio: float = 1.25,
) -> Dict[str, Any]:
    """
    pages: list of {
        "page_num": int,
        "blocks": [{"text": str, "font_size": float, "is_heading": bool (optional)}],
        "ocr_used": bool
    }
    Returns nested JSON: {title, chapter_count, chapters: [{heading, pages: [{page_num, text, ocr_used}]}]}
    """
    median_size = _median_font_size(pages)
    noise = _repeating_lines(pages)

    chapters: List[Dict[str, Any]] = []
    current = {"heading": PREFACE, "pages": []}
    last_was_heading = False  # carried across pages so a heading split over two pages still merges

    for page in pages:
        page_num = page["page_num"]
        ocr_used = page.get("ocr_used", False)
        text_parts: List[str] = []

        for block in page.get("blocks", []):
            text = block["text"].strip()
            if not text or _normalize(text) in noise:
                continue

            if _is_heading(block, median_size, size_ratio):
                if last_was_heading and not current["pages"] and not text_parts:
                    # second line of a multi-line heading, e.g. "Chapter 1" + "Introduction"
                    current["heading"] += " " + text
                else:
                    # flush text gathered so far on this page into the old chapter
                    if text_parts:
                        current["pages"].append({
                            "page_num": page_num,
                            "text": "\n".join(text_parts).strip(),
                            "ocr_used": ocr_used,
                        })
                        text_parts = []
                    chapters.append(current)
                    current = {"heading": text, "pages": []}
                last_was_heading = True
            else:
                text_parts.append(text)
                last_was_heading = False

        if text_parts:
            current["pages"].append({
                "page_num": page_num,
                "text": "\n".join(text_parts).strip(),
                "ocr_used": ocr_used,
            })

    chapters.append(current)
    chapters = [c for c in chapters if c["pages"]]  # drops empty Preface and heading-only chapters

    return {
        "title": title,
        "chapter_count": len(chapters),
        "chapters": chapters,
    }
