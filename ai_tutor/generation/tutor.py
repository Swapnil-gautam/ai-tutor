"""AI Tutor: answer student questions grounded in course materials."""

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


SYSTEM_PROMPT = (
    'You are an AI tutor for the university course "{course_title}". '
    "Your role is to help students understand the course material.\n\n"
    "Rules:\n"
    "- Answer ONLY using the provided lecture materials below.\n"
    "- If the answer spans multiple lectures, explicitly reference which lectures.\n"
    "- Cite your sources as [Lecture X, Slide Y] when referencing specific content.\n"
    "- If you are unsure or the materials do not contain the answer, say so honestly.\n"
    "- Do NOT make up information or use knowledge outside the provided materials.\n"
    "- Explain concepts clearly, as if speaking to a student who is studying.\n"
    "- Use LaTeX notation for any mathematical expressions.\n"
)


def _format_context(retrieved: list[dict]) -> str:
    """Format retrieved chunks into a context block for the LLM."""
    parts = []
    for i, chunk in enumerate(retrieved):
        meta = chunk.get("metadata", {})
        lecture_num = meta.get("lecture_number", "?")
        lecture_title = meta.get("lecture_title", "")
        page_num = meta.get("page_number", "?")
        source = meta.get("source_file", "")
        chunk_type = meta.get("chunk_type", "slide")

        if chunk_type == "lecture_summary":
            header = f"[Lecture {lecture_num} Summary: {lecture_title}]"
        elif chunk_type == "topic_summary":
            header = "[Cross-Lecture Topic Summary]"
        else:
            header = f"[Lecture {lecture_num}, Slide {page_num} — {source}]"

        parts.append(f"--- Source {i + 1}: {header} ---\n{chunk['text']}")

    return "\n\n".join(parts)


def _extract_sources(retrieved: list[dict]) -> list[dict]:
    """Extract source references from retrieved chunks."""
    sources = []
    seen = set()
    for chunk in retrieved:
        meta = chunk.get("metadata", {})
        key = (meta.get("lecture_number", 0), meta.get("page_number", 0))
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "lecture_number": meta.get("lecture_number"),
            "lecture_title": meta.get("lecture_title", ""),
            "page_number": meta.get("page_number"),
            "source_file": meta.get("source_file", ""),
            "chunk_type": meta.get("chunk_type", "slide"),
        })
    return sources


async def ask_tutor(course_id: str, course_title: str, question: str) -> dict:
    """
    Full tutor pipeline:
    1. Retrieve relevant chunks via hybrid search
    2. Build prompt with context
    3. Generate answer with Gemini
    4. Return structured response with citations
    """
    retrieved = hybrid_retrieve(course_id, question)

    if not retrieved:
        return {
            "answer": "I couldn't find any relevant information in the course materials to answer your question.",
            "sources": [],
            "chunks_retrieved": 0,
        }

    context = _format_context(retrieved)
    sources = _extract_sources(retrieved)

    system = SYSTEM_PROMPT.format(course_title=course_title)

    prompt = (
        f"{system}\n\n"
        f"=== COURSE MATERIALS ===\n{context}\n"
        f"=== END MATERIALS ===\n\n"
        f"Student Question: {question}\n\n"
        f"Please provide a thorough, well-structured answer."
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        answer = response.text or "I was unable to generate an answer."
    except Exception:
        logger.exception("Gemini generation failed")
        answer = "An error occurred while generating the answer. Please try again."

    return {
        "answer": answer,
        "sources": sources,
        "chunks_retrieved": len(retrieved),
    }
