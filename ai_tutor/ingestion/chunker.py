"""Semantic chunking: convert extracted pages into indexed chunks."""

import logging
import uuid

from scholera.config import settings

logger = logging.getLogger(__name__)


def create_chunks(
    pages: list[dict],
    course_id: str,
    material_id: str,
    lecture_number: int | None,
    lecture_title: str,
    source_file: str,
) -> list[dict]:
    """
    Convert extractor page dicts into chunk dicts ready for storage.

    Each page becomes one chunk. Pages exceeding max_chunk_tokens are split
    into sub-chunks with overlap.
    """
    chunks = []

    for page in pages:
        text_content = page["text"]
        visual_desc = page.get("visual_description", "")

        combined = _merge_text_and_vision(text_content, visual_desc)
        if not combined.strip():
            continue

        token_est = len(combined.split())

        if token_est <= settings.max_chunk_tokens:
            chunks.append(_make_chunk(
                course_id=course_id,
                material_id=material_id,
                lecture_number=lecture_number,
                lecture_title=lecture_title,
                page_number=page["page_number"],
                chunk_type="slide",
                text_content=text_content,
                visual_description=visual_desc,
                combined_text=combined,
                has_equations=page.get("has_equations", False),
                has_images=page.get("has_images", False),
                source_file=source_file,
            ))
        else:
            sub_chunks = _split_long_text(combined, settings.max_chunk_tokens, settings.chunk_overlap_tokens)
            for idx, sub_text in enumerate(sub_chunks):
                chunks.append(_make_chunk(
                    course_id=course_id,
                    material_id=material_id,
                    lecture_number=lecture_number,
                    lecture_title=lecture_title,
                    page_number=page["page_number"],
                    chunk_type="slide",
                    text_content=text_content if idx == 0 else "",
                    visual_description=visual_desc if idx == 0 else "",
                    combined_text=sub_text,
                    has_equations=page.get("has_equations", False),
                    has_images=page.get("has_images", False),
                    source_file=source_file,
                ))

    logger.info("Created %d chunks from %d pages", len(chunks), len(pages))
    return chunks


def _merge_text_and_vision(text: str, vision_desc: str) -> str:
    parts = []
    if text.strip():
        parts.append(text.strip())
    if vision_desc.strip():
        parts.append(f"[Visual content description]\n{vision_desc.strip()}")
    return "\n\n".join(parts)


def _split_long_text(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_tokens, len(words))
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = end - overlap_tokens
    return chunks


def _make_chunk(**kwargs) -> dict:
    return {"id": uuid.uuid4().hex[:12], **kwargs}
