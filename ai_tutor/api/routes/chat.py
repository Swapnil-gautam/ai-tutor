"""Chat sessions and messaging — supports both RAG and raw Gemini modes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scholera.generation.api_errors import format_client_error
from scholera.generation.direct_gemini import ask_gemini_direct
from scholera.generation.study_guide import generate_study_guide
from scholera.generation.tutor import ask_tutor
from scholera.storage import metadata_db as db

router = APIRouter()


class ChatCreate(BaseModel):
    course_id: str | None = None
    mode: str = "rag"
    title: str = "New Chat"


class ChatMessage(BaseModel):
    content: str


class ChatUpdate(BaseModel):
    title: str | None = None
    mode: str | None = None


class StudyGuideRequest(BaseModel):
    topic: str


@router.get("/sessions")
def list_sessions(course_id: str | None = None):
    return db.list_chat_sessions(course_id)


@router.post("/sessions", status_code=201)
def create_session(body: ChatCreate):
    if body.course_id:
        course = db.get_course(body.course_id)
        if not course:
            raise HTTPException(404, "Course not found")
    return db.create_chat_session(body.course_id, body.mode, body.title)


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    session = db.get_chat_session(session_id)
    if not session:
        raise HTTPException(404, "Chat session not found")
    return session


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, body: ChatUpdate):
    session = db.get_chat_session(session_id)
    if not session:
        raise HTTPException(404, "Chat session not found")
    fields = {}
    if body.title is not None:
        fields["title"] = body.title
    if body.mode is not None:
        if body.mode not in ("rag", "raw"):
            raise HTTPException(422, "mode must be 'rag' or 'raw'")
        fields["mode"] = body.mode
    if not fields:
        return session
    return db.update_chat_session(session_id, **fields)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    session = db.get_chat_session(session_id)
    if not session:
        raise HTTPException(404, "Chat session not found")
    db.delete_chat_session(session_id)


@router.get("/sessions/{session_id}/messages")
def get_messages(session_id: str):
    session = db.get_chat_session(session_id)
    if not session:
        raise HTTPException(404, "Chat session not found")
    return db.get_chat_messages(session_id)


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: ChatMessage):
    session = db.get_chat_session(session_id)
    if not session:
        raise HTTPException(404, "Chat session not found")

    db.add_chat_message(session_id, "user", body.content)

    mode = session.get("mode", "rag")
    course_id = session.get("course_id")

    try:
        if mode == "rag" and course_id:
            course = db.get_course(course_id)
            course_title = course["title"] if course else "Unknown Course"
            result = await ask_tutor(course_id, course_title, body.content)
            answer = result["answer"]
            sources = result.get("sources", [])
        else:
            answer = ask_gemini_direct(body.content, system_instruction=None)
            sources = []
    except Exception as e:
        friendly = format_client_error(e)
        detail = friendly or str(e)
        db.add_chat_message(session_id, "assistant", f"Error: {detail}", [])
        raise HTTPException(status_code=502, detail=detail)

    msg = db.add_chat_message(session_id, "assistant", answer, sources)

    # Auto-title: if this is the first real exchange, set the title from the question
    messages = db.get_chat_messages(session_id)
    if len(messages) <= 2 and session.get("title") == "New Chat":
        short_title = body.content[:60] + ("..." if len(body.content) > 60 else "")
        db.update_chat_session(session_id, title=short_title)

    return msg


@router.post("/study-guide")
async def study_guide_endpoint(body: StudyGuideRequest, course_id: str | None = None):
    """Generate a NotebookLM-style study guide for a topic from course materials."""
    if not course_id:
        raise HTTPException(400, "course_id query parameter is required for study guides")
    course = db.get_course(course_id)
    if not course:
        raise HTTPException(404, "Course not found")
    try:
        return await generate_study_guide(course_id, course["title"], body.topic)
    except Exception as e:
        friendly = format_client_error(e)
        raise HTTPException(status_code=502, detail=friendly or str(e))
