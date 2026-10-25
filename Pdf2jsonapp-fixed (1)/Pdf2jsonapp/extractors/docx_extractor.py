"""
DOCX extraction: groups paragraphs into pseudo-pages and tags headings so
the same json_builder used for PDFs can process Word files.

Word files don't store pagination (it's computed when rendering), so pages
are split on explicit page breaks and on Word's own "last rendered page
break" markers when present. Documents with neither end up as one page.
"""

import io
from typing import Any, Dict, List

from docx import Document

_PAGE_BREAK_XPATHS = (
    './/w:br[@w:type="page"]',
    ".//w:lastRenderedPageBreak",
)


def _style_font_size(paragraph) -> float:
    """Best-effort font size: run-level, then style (walking base styles), else 12."""
    for run in paragraph.runs:
        if run.font and run.font.size:
            return run.font.size.pt
    style = paragraph.style
    while style is not None:
        if style.font and style.font.size:
            return style.font.size.pt
        style = style.base_style
    return 12.0


def _heading_level(paragraph) -> int:
    """0 = not a heading, 1 = Title/Heading 1, 2 = Heading 2, 3+ = deeper."""
    name = (paragraph.style.name or "").lower() if paragraph.style else ""
    if name == "title" or name.startswith("heading 1"):
        return 1
    if name.startswith("heading"):
        digits = "".join(ch for ch in name if ch.isdigit())
        return int(digits) if digits else 2
    return 0


def _has_page_break(paragraph) -> bool:
    return any(paragraph._p.xpath(xp) for xp in _PAGE_BREAK_XPATHS)


def extract_docx(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Returns a list of pseudo-page dicts matching the PDF extractor's shape:
        {"page_num": int, "blocks": [{"text": str, "font_size": float, "is_heading": bool}],
         "ocr_used": False}
    Only top-level Heading 1 / Title paragraphs are flagged as chapter headings.
    """
    doc = Document(io.BytesIO(file_bytes))
    pages: List[Dict[str, Any]] = []
    current_blocks: List[Dict[str, Any]] = []
    page_num = 1

    def flush():
        nonlocal current_blocks, page_num
        if current_blocks:
            pages.append({"page_num": page_num, "blocks": current_blocks, "ocr_used": False})
        current_blocks = []
        page_num += 1

    for paragraph in doc.paragraphs:
        # a break marker at the start of a paragraph means this paragraph is on a new page
        if _has_page_break(paragraph) and current_blocks:
            flush()

        text = paragraph.text.strip()
        if text:
            current_blocks.append({
                "text": text,
                "font_size": _style_font_size(paragraph),
                "is_heading": _heading_level(paragraph) == 1,
            })

    flush()
    return pages
