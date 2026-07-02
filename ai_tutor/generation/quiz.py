"""Generate quizzes from course materials using Gemini."""

from __future__ import annotations

import json
import logging
import re

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


_QUIZ_SYSTEM_PROMPT = (
    'You are a quiz generator for the university course "{course_title}". '
    "Create multiple-choice questions that test understanding of the material.\n\n"
    "Rules:\n"
    "- Base ALL questions on the provided lecture materials below.\n"
    "- Each question must have exactly 4 options: A, B, C, D.\n"
    "- Exactly one option must be correct.\n"
    "- Include a brief explanation for why the correct answer is right.\n"
    "- Questions should range from conceptual understanding to application.\n"
    "- Do NOT create trivial or trick questions.\n"
    "- Use LaTeX notation for mathematical expressions if needed.\n\n"
    "CRITICAL JSON RULES:\n"
    "- Respond with valid JSON only — no markdown, no code fences, no trailing commas.\n"
    "- Every backslash in strings MUST be doubled: write \\\\frac not \\frac.\n"
    "- Do not use unescaped newlines inside string values.\n"
    "- Do not include any text before or after the JSON array.\n\n"
    "Return a JSON array of question objects with this exact schema:\n"
    "[\n"
    '  {{\n'
    '    "question_text": "...",\n'
    '    "option_a": "...",\n'
    '    "option_b": "...",\n'
    '    "option_c": "...",\n'
    '    "option_d": "...",\n'
    '    "correct_option": "A",\n'
    '    "explanation": "..."\n'
    '  }}\n'
    "]\n"
)


def _format_context(retrieved: list[dict]) -> str:
    parts = []
    for i, chunk in enumerate(retrieved):
        meta = chunk.get("metadata", {})
        lecture_num = meta.get("lecture_number", "?")
        page_num = meta.get("page_number", "?")
        chunk_type = meta.get("chunk_type", "slide")

        if chunk_type == "lecture_summary":
            header = f"[Lecture {lecture_num} Summary]"
        elif chunk_type == "topic_summary":
            header = "[Topic Summary]"
        else:
            header = f"[Lecture {lecture_num}, Slide {page_num}]"

        parts.append(f"--- Source {i + 1}: {header} ---\n{chunk['text']}")
    return "\n\n".join(parts)


def _sanitize_json(text: str) -> str:
    """Best-effort fixes for common LLM JSON issues."""
    text = re.sub(r",\s*([}\]])", r"\1", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(
        r'(?<=: ")((?:[^"\\]|\\.)*)(?=")',
        lambda m: m.group(0).replace("\n", "\\n"),
        text,
    )
    return text


def _parse_questions(raw_text: str) -> list[dict]:
    """Extract the JSON array from Gemini's response, tolerating common issues."""
    text = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    text = _sanitize_json(text)

    try:
        questions = json.loads(text)
    except json.JSONDecodeError:
        array_match = re.search(r"\[[\s\S]*\]", text)
        if array_match:
            try:
                questions = json.loads(_sanitize_json(array_match.group()))
            except json.JSONDecodeError:
                questions = _extract_objects_individually(text)
        else:
            questions = _extract_objects_individually(text)

    if not isinstance(questions, list):
        raise ValueError("Expected a JSON array of questions")

    valid = []
    for q in questions:
        if all(k in q for k in ("question_text", "option_a", "option_b",
                                 "option_c", "option_d", "correct_option")):
            q["correct_option"] = q["correct_option"].upper().strip()
            if q["correct_option"] in ("A", "B", "C", "D"):
                valid.append(q)
    return valid


def _extract_objects_individually(text: str) -> list[dict]:
    """Fallback: pull out each {...} object and parse them one at a time."""
    results: list[dict] = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                fragment = text[start : i + 1]
                try:
                    obj = json.loads(_sanitize_json(fragment))
                    if isinstance(obj, dict):
                        results.append(obj)
                except json.JSONDecodeError:
                    pass
                start = -1
    return results


async def generate_quiz(
    course_id: str,
    course_title: str,
    topic: str,
    num_questions: int = 5,
    lecture_number: int | None = None,
    lecture_numbers: list[int] | None = None,
) -> dict:
    nums: list[int] = []
    for x in lecture_numbers or []:
        try:
            v = int(x)
            if v > 0:
                nums.append(v)
        except (TypeError, ValueError):
            pass
    nums = sorted(set(nums))
    if not nums and lecture_number is not None:
        try:
            v = int(lecture_number)
            if v > 0:
                nums = [v]
        except (TypeError, ValueError):
            nums = []

    query = topic
    if nums:
        query = f"Lectures {', '.join(str(n) for n in nums)}: {topic}"

    retrieved = hybrid_retrieve(course_id, query, lecture_numbers=nums or None)
    if not retrieved:
        raise ValueError("No relevant course materials found for this topic.")

    context = _format_context(retrieved)
    system = _QUIZ_SYSTEM_PROMPT.format(course_title=course_title)

    scope_line = ""
    if nums:
        lec = ", ".join(str(n) for n in nums)
        scope_line = (
            f"\nIMPORTANT: Base every question ONLY on material from lecture(s) {lec} "
            "among the sources below. Do not invent facts from other lectures.\n"
        )

    client = _get_client()
    all_questions: list[dict] = []
    remaining = num_questions
    max_attempts = 3

    for attempt in range(max_attempts):
        prompt = (
            f"{system}\n\n"
            f"=== COURSE MATERIALS ===\n{context}\n"
            f"=== END MATERIALS ===\n\n"
            f"Generate exactly {remaining} multiple-choice questions about: {topic}.{scope_line}\n"
            f"Return ONLY the JSON array."
        )

        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )

        raw = response.text or ""
        batch = _parse_questions(raw)
        logger.info(
            "Quiz attempt %d: requested %d, parsed %d valid",
            attempt + 1, remaining, len(batch),
        )
        all_questions.extend(batch)

        if len(all_questions) >= num_questions:
            break
        remaining = num_questions - len(all_questions)

    if not all_questions:
        raise ValueError("Failed to generate valid quiz questions. Please try again.")

    return {
        "title": f"Quiz: {topic}",
        "topic": topic,
        "lecture_number": nums[0] if len(nums) == 1 else None,
        "lecture_numbers": nums,
        "questions": all_questions[:num_questions],
    }
