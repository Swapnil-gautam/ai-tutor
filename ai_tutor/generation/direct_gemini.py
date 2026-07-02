"""Direct Gemini calls with no RAG or course context (baseline / comparison)."""

from __future__ import annotations

import logging

from google import genai

from scholera.config import settings

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise ValueError(
                "Gemini API key is not set. Add SCHOLERA_GEMINI_API_KEY to your .env file."
            )
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def ask_gemini_direct(
    question: str,
    system_instruction: str | None = None,
) -> str:
    """
    Send a single user question to Gemini. No retrieval, no course materials.
    """
    client = _get_client()

    if system_instruction and system_instruction.strip():
        prompt = (
            f"{system_instruction.strip()}\n\n"
            f"---\n\n"
            f"{question.strip()}"
        )
    else:
        prompt = question.strip()

    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        return (response.text or "").strip() or "(Empty response from model.)"
    except Exception:
        logger.exception("Direct Gemini call failed")
        raise
