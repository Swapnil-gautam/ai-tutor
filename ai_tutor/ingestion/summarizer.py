"""Hierarchical summarization: lecture-level and topic-level summaries."""

from __future__ import annotations

import logging
import uuid

from google import genai

from scholera.config import settings
from scholera.storage import metadata_db as db

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


LECTURE_SUMMARY_PROMPT = (
    "You are an academic summarizer. Below are the contents of all slides from "
    "Lecture {lecture_number}: \"{lecture_title}\".\n\n"
    "Create a comprehensive summary (400-600 words) that covers:\n"
    "- The main topics and concepts taught\n"
    "- Key definitions, formulas, and theorems\n"
    "- How concepts build on each other within this lecture\n"
    "- Important examples or applications mentioned\n\n"
    "Write in a clear, educational tone. Use LaTeX for any math notation.\n\n"
    "Slide contents:\n{slides_text}"
)

TOPIC_SUMMARY_PROMPT = (
    "You are an academic knowledge organizer. Below are excerpts from multiple "
    "lectures in a course titled \"{course_title}\".\n\n"
    "These excerpts all relate to overlapping topics. Create a synthesis summary "
    "(300-500 words) that:\n"
    "- Identifies the common themes across these lectures\n"
    "- Explains how concepts evolve or connect across lectures\n"
    "- Highlights key relationships and dependencies\n\n"
    "Lecture excerpts:\n{excerpts}"
)


async def generate_lecture_summary(
    course_id: str, material_id: str, lecture_number: int,
    lecture_title: str, chunks: list[dict],
) -> dict | None:
    """Generate a lecture-level summary from all slide chunks of one lecture."""
    if not chunks:
        return None

    slides_text = "\n\n---\n\n".join(
        f"[Slide {c.get('page_number', '?')}]\n{c['combined_text']}" for c in chunks
    )

    # Truncate if too long to fit in context
    if len(slides_text) > 80000:
        slides_text = slides_text[:80000] + "\n\n[... truncated for length ...]"

    prompt = LECTURE_SUMMARY_PROMPT.format(
        lecture_number=lecture_number,
        lecture_title=lecture_title or f"Lecture {lecture_number}",
        slides_text=slides_text,
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        summary_text = response.text or ""
    except Exception:
        logger.exception("Failed to generate lecture summary for lecture %s", lecture_number)
        return None

    summary_chunk = {
        "id": uuid.uuid4().hex[:12],
        "course_id": course_id,
        "material_id": material_id,
        "lecture_number": lecture_number,
        "lecture_title": lecture_title,
        "page_number": 0,
        "chunk_type": "lecture_summary",
        "text_content": summary_text,
        "visual_description": "",
        "combined_text": f"[Lecture {lecture_number} Summary: {lecture_title}]\n{summary_text}",
        "has_equations": False,
        "has_images": False,
        "source_file": "",
    }

    logger.info("Generated lecture summary for Lecture %d (%d chars)", lecture_number, len(summary_text))
    return summary_chunk


async def generate_topic_summaries(course_id: str, course_title: str, material_id: str = "") -> list[dict]:
    """Generate cross-lecture topic summaries by grouping related chunks."""
    all_chunks = db.get_chunks_for_course(course_id, chunk_type="slide")
    if len(all_chunks) < 10:
        logger.info("Too few chunks (%d) for topic summaries, skipping", len(all_chunks))
        return []

    lecture_summaries = db.get_chunks_for_course(course_id, chunk_type="lecture_summary")
    if not lecture_summaries:
        logger.info("No lecture summaries available for topic clustering")
        return []

    excerpts = "\n\n---\n\n".join(
        f"[Lecture {s.get('lecture_number', '?')}: {s.get('lecture_title', '')}]\n{s['combined_text']}"
        for s in lecture_summaries
    )

    if len(excerpts) > 80000:
        excerpts = excerpts[:80000] + "\n\n[... truncated ...]"

    prompt = TOPIC_SUMMARY_PROMPT.format(
        course_title=course_title,
        excerpts=excerpts,
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        summary_text = response.text or ""
    except Exception:
        logger.exception("Failed to generate topic summaries")
        return []

    topic_chunk = {
        "id": uuid.uuid4().hex[:12],
        "course_id": course_id,
        "material_id": material_id,
        "lecture_number": 0,
        "lecture_title": "Cross-lecture Topic Summary",
        "page_number": 0,
        "chunk_type": "topic_summary",
        "text_content": summary_text,
        "visual_description": "",
        "combined_text": f"[Course Topic Summary: {course_title}]\n{summary_text}",
        "has_equations": False,
        "has_images": False,
        "source_file": "",
    }

    logger.info("Generated topic summary (%d chars)", len(summary_text))
    return [topic_chunk]
