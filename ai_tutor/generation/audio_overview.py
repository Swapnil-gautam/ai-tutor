"""Generate a grounded audio explanation for a course topic."""

from __future__ import annotations

import logging
import uuid
import wave
from pathlib import Path

from google import genai
from google.genai import types

from scholera.config import settings
from scholera.retrieval.hybrid_search import hybrid_retrieve

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _format_context(retrieved: list[dict]) -> str:
    parts: list[str] = []
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
    sources = []
    seen = set()
    for chunk in retrieved:
        meta = chunk.get("metadata", {})
        key = (meta.get("lecture_number", 0), meta.get("page_number", 0), meta.get("chunk_type", "slide"))
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            {
                "lecture_number": meta.get("lecture_number"),
                "lecture_title": meta.get("lecture_title", ""),
                "page_number": meta.get("page_number"),
                "source_file": meta.get("source_file", ""),
                "chunk_type": meta.get("chunk_type", "slide"),
            }
        )
    return sources


SCRIPT_SYSTEM = (
    'You are an expert teaching assistant for the university course "{course_title}".\n'
    "You will write a short spoken explanation for a student.\n\n"
    "Rules:\n"
    "- Use ONLY the provided course materials.\n"
    "- If the materials do not contain enough info, say what is missing.\n"
    "- Do NOT include inline citations like [Lecture X, Slide Y] in the script (citations will be shown separately).\n"
    "- Keep it clear and engaging, like a mini-lecture.\n"
    "- Prefer concrete examples and definitions if present in the materials.\n"
    "- Avoid reading out filenames or slide numbers.\n"
)


def _build_script_prompt(course_title: str, topic: str, context: str) -> str:
    system = SCRIPT_SYSTEM.format(course_title=course_title)
    return (
        f"{system}\n\n"
        f"=== COURSE MATERIALS ===\n{context}\n"
        f"=== END MATERIALS ===\n\n"
        f"Topic: {topic}\n\n"
        "Write a spoken script (~3-5 minutes). Use short paragraphs and natural transitions."
    )


def _strip_for_speech(text: str) -> str:
    # Keep it simple: remove obvious markdown-ish headers that sound odd when spoken.
    lines = []
    for line in (text or "").splitlines():
        if line.strip().startswith(("##", "###", "#")):
            lines.append(line.lstrip("#").strip())
        else:
            lines.append(line)
    return "\n".join(lines).strip()


async def generate_audio_overview(course_id: str, course_title: str, topic: str) -> dict:
    retrieved = hybrid_retrieve(course_id, topic)
    if not retrieved:
        return {
            "script": "I couldn't find relevant information in the course materials for that topic.",
            "sources": [],
            "chunks_retrieved": 0,
            "audio_id": None,
            "audio_url": None,
        }

    context = _format_context(retrieved)
    sources = _extract_sources(retrieved)
    prompt = _build_script_prompt(course_title, topic, context)

    client = _get_client()

    script_resp = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
    )
    script = (script_resp.text or "").strip() or "I was unable to generate a script."

    speech_text = _strip_for_speech(script)
    audio_id = uuid.uuid4().hex[:16]
    out_path = Path(settings.audio_dir) / f"{audio_id}.wav"

    tts_resp = client.models.generate_content(
        model=settings.gemini_tts_model,
        contents=speech_text,
        config=types.GenerateContentConfig(
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=settings.gemini_tts_voice
                    )
                ),
                language_code=settings.gemini_tts_language,
            ),
        ),
    )

    audio_bytes: bytes | None = None
    try:
        # Typical location: first candidate, first part has inline_data bytes.
        cand = (tts_resp.candidates or [None])[0]
        if cand and cand.content and cand.content.parts:
            for part in cand.content.parts:
                if getattr(part, "inline_data", None) and getattr(part.inline_data, "data", None):
                    audio_bytes = part.inline_data.data
                    break
    except Exception:
        logger.exception("Failed to extract audio bytes from TTS response")

    if not audio_bytes:
        return {
            "script": script,
            "sources": sources,
            "chunks_retrieved": len(retrieved),
            "audio_id": None,
            "audio_url": None,
            "error": "TTS returned no audio data.",
        }

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)       # 16-bit
        wf.setframerate(24000)   # Gemini TTS outputs 24 kHz PCM
        wf.writeframes(audio_bytes)

    return {
        "script": script,
        "sources": sources,
        "chunks_retrieved": len(retrieved),
        "audio_id": audio_id,
        "audio_url": f"/audio/{audio_id}.wav",
    }

