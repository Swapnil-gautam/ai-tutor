"""Ingestion pipeline: orchestrates extraction, vision, chunking, embedding, and summarization."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from scholera.config import settings
from scholera.ingestion.chunker import create_chunks
from scholera.ingestion.extractors.pdf_extractor import extract_pdf
from scholera.ingestion.extractors.ppt_extractor import extract_pptx
from scholera.ingestion.summarizer import generate_lecture_summary, generate_topic_summaries
from scholera.ingestion.vision import describe_slide_image, should_use_vision
from scholera.storage import metadata_db as db
from scholera.storage import vector_store

logger = logging.getLogger(__name__)


def _progress(material_id: str, step: str, pct: int = 0):
    db.update_material_progress(material_id, "processing", step, pct)
    logger.info("[%s] %s (%d%%)", material_id[:8], step, pct)


def run_ingestion(material_id: str, file_path: str):
    """Entry point called from the background task. Wraps the async pipeline."""
    asyncio.run(_run_ingestion_async(material_id, file_path))


async def _run_ingestion_async(material_id: str, file_path: str):
    material = db.get_material(material_id)
    if not material:
        logger.error("Material %s not found", material_id)
        return

    course_id = material["course_id"]
    course = db.get_course(course_id)

    try:
        # --- Step 1: Extract text ---
        _progress(material_id, "Extracting text from document", 5)
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            extracted = extract_pdf(file_path, material_id)
        elif ext in (".pptx", ".ppt"):
            extracted = extract_pptx(file_path, material_id)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        db.update_material(material_id, page_count=extracted["page_count"])
        logger.info("Extracted %d pages from %s", extracted["page_count"], Path(file_path).name)

        # --- Step 2: Vision pass for low-text-density pages ---
        vision_pages = [p for p in extracted["pages"] if should_use_vision(p)] if settings.gemini_api_key else []
        total_vision = len(vision_pages)

        if total_vision > 0:
            _progress(material_id, f"Analyzing {total_vision} visual slides with AI", 20)
            for idx, page in enumerate(vision_pages):
                pct = 20 + int((idx / total_vision) * 40)
                _progress(material_id, f"Vision pass: slide {page['page_number']} ({idx+1}/{total_vision})", pct)
                desc = await describe_slide_image(page["image_path"])
                page["visual_description"] = desc
        else:
            if not settings.gemini_api_key:
                logger.warning("No Gemini API key — skipping vision pass")

        for page in extracted["pages"]:
            page.setdefault("visual_description", "")

        # --- Step 3: Chunk ---
        _progress(material_id, "Chunking pages", 65)
        chunks = create_chunks(
            pages=extracted["pages"],
            course_id=course_id,
            material_id=material_id,
            lecture_number=material.get("lecture_number"),
            lecture_title=material.get("lecture_title", ""),
            source_file=material["filename"],
        )

        if not chunks:
            logger.warning("No chunks produced for material %s", material_id)
            db.update_material(material_id, status="completed")
            return

        # --- Step 4: Embedding + storing ---
        _progress(material_id, f"Embedding {len(chunks)} chunks", 70)
        db.insert_chunks(chunks)
        vector_store.add_chunks(course_id, chunks)
        logger.info("Stored %d chunks in DB and vector store", len(chunks))

        # --- Step 5: Lecture summary ---
        if settings.gemini_api_key and material.get("lecture_number"):
            _progress(material_id, "Generating lecture summary", 85)
            summary = await generate_lecture_summary(
                course_id=course_id,
                material_id=material_id,
                lecture_number=material["lecture_number"],
                lecture_title=material.get("lecture_title", ""),
                chunks=chunks,
            )
            if summary:
                db.insert_chunks([summary])
                vector_store.add_chunks(course_id, [summary])

            _progress(material_id, "Generating topic summaries", 92)
            topic_summaries = await generate_topic_summaries(
                course_id, course.get("title", ""), material_id
            )
            if topic_summaries:
                db.insert_chunks(topic_summaries)
                vector_store.add_chunks(course_id, topic_summaries)

        db.update_material(material_id, status="completed")
        logger.info("Ingestion complete for material %s", material_id)

    except Exception:
        logger.exception("Ingestion failed for material %s", material_id)
        db.update_material(material_id, status="failed")
