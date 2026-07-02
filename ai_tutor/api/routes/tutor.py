from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scholera.generation.api_errors import format_client_error
from scholera.generation.tutor import ask_tutor
from scholera.storage import metadata_db as db

router = APIRouter()


class TutorQuery(BaseModel):
    question: str


@router.post("/ask")
async def ask_question(course_id: str, body: TutorQuery):
    course = db.get_course(course_id)
    if not course:
        raise HTTPException(404, "Course not found")
    try:
        return await ask_tutor(course_id, course["title"], body.question)
    except Exception as e:
        friendly = format_client_error(e)
        if friendly:
            from google.genai.errors import ClientError

            status = 429 if isinstance(e, ClientError) and e.code == 429 else 502
            raise HTTPException(status_code=status, detail=friendly)
        raise HTTPException(status_code=502, detail=str(e))
