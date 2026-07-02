"""Study Guide generator — NotebookLM-style deep concept explanations from course materials."""

from __future__ import annotations

import logging

from google import genai

from scholera.config import settings
from scholera.retrieval.hybrid_search import hybrid_retrieve

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


STUDY_GUIDE_PROMPT = (
    'You are Scholera AI, an expert study coach for the course "{course_title}". '
    "A student wants to deeply understand a topic. Using ONLY the provided lecture materials, "
    "create a comprehensive study guide.\n\n"
    "Structure your response as:\n"
    "## Overview\n"
    "A 2-3 sentence summary of what this topic is about.\n\n"
    "## Key Concepts\n"
    "List and explain each key concept, one by one. Use simple language and analogies.\n\n"
    "## How It All Connects\n"
    "Explain how these concepts relate to each other and to the broader course.\n\n"
    "## Common Misconceptions\n"
    "What do students often get wrong about this topic?\n\n"
    "## Practice Questions\n"
    "Generate 3 practice questions (with answers) to test understanding.\n\n"
    "Rules:\n"
    "- Draw ONLY from the provided materials.\n"
    "- Cite sources as [Lecture X, Slide Y].\n"
    "- Use LaTeX for any math: $...$.\n"
    "- Explain step by step, as if tutoring a student one-on-one.\n"
)


async def generate_study_guide(course_id: str, course_title: str, topic: str) -> dict:
    retrieved = hybrid_retrieve(course_id, topic, top_k=12)

    if not retrieved:
        return {
            "guide": "I couldn't find enough material on this topic in the course.",
            "sources": [],
            "chunks_retrieved": 0,
        }

    context_parts = []
    sources = []
    seen = set()
    for chunk in retrieved:
        meta = chunk.get("metadata", {})
        lnum = meta.get("lecture_number", "?")
        pnum = meta.get("page_number", "?")
        src = meta.get("source_file", "")
        ctype = meta.get("chunk_type", "slide")

        header = f"[Lecture {lnum}, Slide {pnum} — {src}]" if ctype == "slide" else f"[{ctype}]"
        context_parts.append(f"--- {header} ---\n{chunk['text']}")

        key = (lnum, pnum)
        if key not in seen:
            seen.add(key)
            sources.append({
                "lecture_number": meta.get("lecture_number"),
                "page_number": meta.get("page_number"),
                "source_file": src,
                "chunk_type": ctype,
            })

    context = "\n\n".join(context_parts)
    prompt = (
        f"{STUDY_GUIDE_PROMPT.format(course_title=course_title)}\n\n"
        f"=== COURSE MATERIALS ===\n{context}\n=== END MATERIALS ===\n\n"
        f"Topic the student wants to study: {topic}"
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        guide_text = response.text or "Unable to generate study guide."
    except Exception:
        logger.exception("Study guide generation failed")
        raise

    return {
        "guide": guide_text,
        "sources": sources,
        "chunks_retrieved": len(retrieved),
    }
