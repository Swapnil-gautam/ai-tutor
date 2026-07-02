"""Gemini Vision pass: generate rich textual descriptions of visual slide content."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from google import genai

from scholera.config import settings

logger = logging.getLogger(__name__)

_client: genai.Client | None = None

VISION_PROMPT = (
    "You are an expert teaching assistant. Describe the academic content of this "
    "lecture slide in detail. Include:\n"
    "- Any text visible on the slide\n"
    "- Descriptions of diagrams, charts, figures, and their meaning\n"
    "- Any mathematical equations or formulas, written in LaTeX notation\n"
    "- What a student should understand from this slide\n\n"
    "Be thorough but concise. Focus on the educational content, not visual styling."
)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


async def describe_slide_image(image_path: str) -> str:
    """Send a slide image to Gemini Vision and get a textual description."""
    path = Path(image_path)
    if not path.exists():
        logger.warning("Image not found: %s", image_path)
        return ""

    try:
        client = _get_client()
        image_bytes = path.read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                {
                    "parts": [
                        {"text": VISION_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": image_b64,
                            }
                        },
                    ]
                }
            ],
        )
        description = response.text or ""
        logger.debug("Vision description for %s: %d chars", path.name, len(description))
        return description

    except Exception:
        logger.exception("Gemini Vision failed for %s", image_path)
        return ""


def should_use_vision(page: dict) -> bool:
    """Decide whether a page needs the vision pass based on text density."""
    if not page.get("image_path"):
        return False
    text_density = page.get("text_density", 0)
    if text_density < settings.text_density_threshold:
        return True
    if page.get("has_images"):
        return True
    return False
