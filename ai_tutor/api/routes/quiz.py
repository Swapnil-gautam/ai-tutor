"""Quiz generation and management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scholera.generation.api_errors import format_client_error
from scholera.generation.quiz import generate_quiz
from scholera.storage import metadata_db as db

router = APIRouter()


class QuizGenerateRequest(BaseModel):
    topic: str
    num_questions: int = 5
    lecture_number: int | None = None
    lecture_numbers: list[int] | None = None


@router.post("/generate", status_code=201)
async def generate_quiz_endpoint(course_id: str, body: QuizGenerateRequest):
    course = db.get_course(course_id)
    if not course:
        raise HTTPException(404, "Course not found")

    topic = (body.topic or "").strip()
    if not topic:
        raise HTTPException(400, "topic is required")

    nums: list[int] = []
    if body.lecture_numbers:
        for x in body.lecture_numbers:
            try:
                v = int(x)
                if v > 0:
                    nums.append(v)
            except (TypeError, ValueError):
                pass
        nums = sorted(set(nums))
    if not nums and body.lecture_number is not None:
        try:
            v = int(body.lecture_number)
            if v > 0:
                nums = [v]
        except (TypeError, ValueError):
            nums = []

    try:
        result = await generate_quiz(
            course_id, course["title"], topic,
            num_questions=body.num_questions,
            lecture_number=body.lecture_number,
            lecture_numbers=nums or None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        friendly = format_client_error(e)
        raise HTTPException(502, friendly or str(e))

    quiz = db.create_quiz(
        course_id=course_id,
        title=result["title"],
        lecture_number=result.get("lecture_number"),
        topic=result["topic"],
        questions=result["questions"],
        lecture_numbers=result.get("lecture_numbers") or [],
    )

    return {**quiz, "questions": db.get_quiz_questions(quiz["id"])}


@router.get("/")
def list_quizzes(course_id: str):
    return db.list_quizzes(course_id)


@router.get("/{quiz_id}")
def get_quiz(course_id: str, quiz_id: str):
    quiz = db.get_quiz(quiz_id)
    if not quiz or quiz["course_id"] != course_id:
        raise HTTPException(404, "Quiz not found")
    questions = db.get_quiz_questions(quiz_id)
    return {**quiz, "questions": questions}


@router.delete("/{quiz_id}", status_code=204)
def delete_quiz(course_id: str, quiz_id: str):
    quiz = db.get_quiz(quiz_id)
    if not quiz or quiz["course_id"] != course_id:
        raise HTTPException(404, "Quiz not found")
    db.delete_quiz(quiz_id)
    return None
