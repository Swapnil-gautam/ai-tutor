from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scholera.config import settings
from scholera.generation.api_errors import format_client_error
from scholera.generation.audio_overview import generate_audio_overview
from scholera.storage import metadata_db as db

course_router = APIRouter()
public_router = APIRouter()


class AudioOverviewRequest(BaseModel):
    topic: str


@course_router.post("/overview")
async def audio_overview(course_id: str, body: AudioOverviewRequest):
    course = db.get_course(course_id)
    if not course:
        raise HTTPException(404, "Course not found")
    topic = (body.topic or "").strip()
    if not topic:
        raise HTTPException(400, "topic is required")
    try:
        return await generate_audio_overview(course_id, course["title"], topic)
    except Exception as e:
        friendly = format_client_error(e)
        raise HTTPException(status_code=502, detail=friendly or str(e))


@public_router.get("/{audio_file}")
def get_audio(audio_file: str):
    # Only serve files from audio_dir.
    if "/" in audio_file or "\\" in audio_file:
        raise HTTPException(400, "Invalid audio file")

    p = Path(settings.audio_dir) / audio_file
    if not p.exists():
        raise HTTPException(404, "Audio not found")
    if p.suffix.lower() not in {".wav", ".mp3", ".ogg"}:
        raise HTTPException(400, "Unsupported audio type")

    from fastapi.responses import FileResponse

    # Let the browser stream it; FileResponse sets headers based on filename.
    return FileResponse(str(p))

