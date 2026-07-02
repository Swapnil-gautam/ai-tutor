from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scholera.storage import metadata_db as db

router = APIRouter()


class CourseCreate(BaseModel):
    title: str
    description: str = ""


@router.post("/", status_code=201)
def create_course(body: CourseCreate):
    return db.create_course(body.title, body.description)


@router.get("/")
def list_courses():
    return db.list_courses()


@router.get("/{course_id}")
def get_course(course_id: str):
    course = db.get_course(course_id)
    if not course:
        raise HTTPException(404, "Course not found")
    return course


@router.get("/{course_id}/stats")
def get_stats(course_id: str):
    course = db.get_course(course_id)
    if not course:
        raise HTTPException(404, "Course not found")
    return db.get_course_stats(course_id)
