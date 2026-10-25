"""
PDF extraction: pulls text lines with font-size metadata (for heading
detection) from each page, using OCR fallback for scanned/image pages.
"""

from typing import Any, Callable, Dict, List, Optional

import fitz  # PyMuPDF

from utils.ocr_fallback import needs_ocr, ocr_page, tesseract_available


def extract_pdf(
    file_bytes: bytes,
    ocr_enabled: bool = True,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Returns a list of page dicts:
        {"page_num": int, "blocks": [{"text": str, "font_size": float}], "ocr_used": bool}

    progress_callback(current_page, total_pages) is called after each page,
    useful for driving a Streamlit progress bar.

    OCR is skipped silently if the tesseract binary isn't installed.
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        if doc.needs_pass:
            raise ValueError("This PDF is password-protected. Remove the password and try again.")

        ocr_enabled = ocr_enabled and tesseract_available()
        pages_out: List[Dict[str, Any]] = []
        total = len(doc)

        for i, page in enumerate(doc):
            page_dict = page.get_text("dict", sort=True)
            blocks_out = []

            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:  # 0 = text block, 1 = image block
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    line_text = "".join(span["text"] for span in spans).strip()
                    if not line_text:
                        continue
                    # use the largest span size as representative of the line
                    font_size = max(span["size"] for span in spans)
                    blocks_out.append({"text": line_text, "font_size": round(font_size, 1)})

            ocr_used = False
            if ocr_enabled and needs_ocr(" ".join(b["text"] for b in blocks_out)):
                ocr_text = ocr_page(page)
                if ocr_text:
                    blocks_out = [{"text": ln.strip(), "font_size": 12.0}
                                  for ln in ocr_text.splitlines() if ln.strip()]
                    ocr_used = True

            pages_out.append({"page_num": i + 1, "blocks": blocks_out, "ocr_used": ocr_used})

            if progress_callback:
                progress_callback(i + 1, total)

        return pages_out
    finally:
        doc.close()
