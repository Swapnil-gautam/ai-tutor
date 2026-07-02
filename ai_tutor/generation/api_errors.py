"""User-friendly messages for Gemini API failures."""

from __future__ import annotations


def format_client_error(exc: BaseException) -> str | None:
    """Return a short, actionable message for known API errors; else None."""
    try:
        from google.genai.errors import ClientError
    except ImportError:
        return None

    if not isinstance(exc, ClientError):
        return None

    if exc.code == 429:
        return (
            "Gemini returned 429 RESOURCE_EXHAUSTED (quota / rate limit).\n\n"
            "What this usually means:\n"
            "  • Free-tier requests per minute (RPM) or tokens per minute (TPM) were hit — "
            "wait about 1 minute and try again.\n"
            "  • Daily free quota for this model may be exhausted — check "
            "https://aistudio.google.com/ and https://ai.google.dev/gemini-api/docs/rate-limits\n"
            "  • Some projects show 'limit: 0' until billing is enabled or the API is fully enabled.\n\n"
            "Things to try:\n"
            "  1. Wait 1–2 minutes, then run the command again.\n"
            "  2. In .env set SCHOLERA_GEMINI_MODEL to another model your key can use "
            "(e.g. gemini-2.5-flash or gemini-2.0-flash-lite — see AI Studio model list).\n"
            "  3. Enable billing or upgrade quota in Google AI Studio if you need higher limits.\n"
        )

    if exc.code == 400:
        return (
            f"Gemini returned 400 Bad Request. Often the model name is wrong for your API version.\n"
            f"Check SCHOLERA_GEMINI_MODEL in .env against the list at "
            f"https://ai.google.dev/gemini-api/docs/models\n\n"
            f"Details: {exc.message or exc}"
        )

    if exc.code == 401 or exc.code == 403:
        return (
            "Gemini rejected the API key (401/403). Check SCHOLERA_GEMINI_API_KEY in .env "
            "and that the Generative Language API is enabled for the project.\n\n"
            f"Details: {exc.message or exc}"
        )

    return None
