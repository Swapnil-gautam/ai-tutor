"""Extract text and page images from PDF files.

Uses pdftext (fast, no ML models) as the primary extractor for digital PDFs.
Falls back to Marker (ML-based OCR) only when explicitly requested for scanned docs.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pdftext.extraction import paginated_plain_text_output
from pdf2image import convert_from_path

from scholera.config import settings

logger = logging.getLogger(__name__)


def extract_pdf(file_path: str, material_id: str) -> dict:
    """
    Fast extraction using pdftext.  Works in seconds for digital PDFs
    (lecture slides, textbook exports).  No ML models, no GPU needed.

    Returns:
        {
            "pages": [
                {
                    "page_number": int,
                    "text": str,
                    "image_path": str | None,
                    "has_equations": bool,
                    "has_images": bool,
                    "text_density": int,
                }
            ],
            "full_markdown": str,
            "page_count": int,
        }
    """
    path = Path(file_path)
    logger.info("Extracting PDF (pdftext): %s", path.name)

    raw_pages: list[str] = paginated_plain_text_output(str(path))

    images_dir = settings.images_dir / material_id
    images_dir.mkdir(parents=True, exist_ok=True)
    page_images = _render_page_images(str(path), images_dir)

    pages = []
    for i, text in enumerate(raw_pages):
        page_num = i + 1
        img_path = page_images.get(page_num)
        has_eq = _detect_equations(text)

        pages.append({
            "page_number": page_num,
            "text": text.strip(),
            "image_path": str(img_path) if img_path else None,
            "has_equations": has_eq,
            "has_images": img_path is not None,
            "text_density": len(text.strip()),
        })

    full_md = "\n\n---\n\n".join(p["text"] for p in pages if p["text"])

    return {
        "pages": pages,
        "full_markdown": full_md,
        "page_count": len(pages),
    }


def _render_page_images(pdf_path: str, output_dir: Path) -> dict[int, Path]:
    """Render each page to PNG for the Gemini vision pass."""
    try:
        images = convert_from_path(pdf_path, dpi=150)
    except Exception:
        logger.warning("pdf2image failed (is poppler installed?). Skipping image rendering.")
        return {}

    result = {}
    for i, img in enumerate(images):
        page_num = i + 1
        out_path = output_dir / f"page_{page_num}.png"
        img.save(str(out_path), "PNG")
        result[page_num] = out_path
    return result


def _detect_equations(text: str) -> bool:
    patterns = [r"\$.*?\$", r"\\frac", r"\\sum", r"\\int", r"\\begin\{equation", r"\\mathbb", r"\\nabla"]
    return any(re.search(p, text) for p in patterns)
