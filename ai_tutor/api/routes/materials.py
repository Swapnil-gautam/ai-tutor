from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks

from scholera.config import settings
from scholera.storage import metadata_db as db
from scholera.ingestion.pipeline import run_ingestion

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".pptx", ".ppt"}


@router.post("/", status_code=202)
async def upload_material(
    course_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    lecture_number: int | None = Form(None),
    lecture_title: str = Form(""),
):
    course = db.get_course(course_id)
    if not course:
        raise HTTPException(404, "Course not found")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}. Allowed: {ALLOWED_EXTENSIONS}")

    material = db.create_material(
        course_id=course_id,
        filename=file.filename,
        file_type=ext.lstrip("."),
        lecture_number=lecture_number,
        lecture_title=lecture_title,
    )

    upload_path = settings.uploads_dir / f"{material['id']}{ext}"
    with open(upload_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    background_tasks.add_task(run_ingestion, material["id"], str(upload_path))

    return {"material_id": material["id"], "status": "processing"}


@router.delete("/{material_id}", status_code=204)
def delete_material(course_id: str, material_id: str):
    material = db.get_material(material_id)
    if not material:
        raise HTTPException(404, "Material not found")
    if material["course_id"] != course_id:
        raise HTTPException(404, "Material not found in this course")

    from scholera.storage import vector_store
    try:
        collection = vector_store.get_collection(course_id)
        existing = collection.get(where={"material_id": material_id})
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception:
        pass  # vector store cleanup is best-effort

    db.delete_material(material_id)

    upload_path = settings.uploads_dir / f"{material_id}.{material['file_type']}"
    if upload_path.exists():
        upload_path.unlink()

    return None


@router.get("/")
def list_materials(course_id: str):
    return db.list_materials(course_id)


@router.get("/{material_id}/status")
def get_material_status(material_id: str):
    mat = db.get_material(material_id)
    if not mat:
        raise HTTPException(404, "Material not found")
    progress = db.get_material_progress(material_id)
    return {
        "material_id": mat["id"],
        "status": progress["status"],
        "step": progress["step"],
        "progress": progress["progress"],
        "page_count": mat["page_count"],
    }
