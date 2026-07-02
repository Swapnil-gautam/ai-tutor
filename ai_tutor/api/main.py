from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from scholera.api.routes import courses, materials, tutor, chat, audio, quiz
from scholera.storage.metadata_db import init_db

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Scholera AI",
    description="AI-native Learning Management System backend",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(courses.router, prefix="/courses", tags=["courses"])
app.include_router(materials.router, prefix="/courses/{course_id}/materials", tags=["materials"])
app.include_router(tutor.router, prefix="/courses/{course_id}/tutor", tags=["tutor"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(audio.course_router, prefix="/courses/{course_id}/audio", tags=["audio"])
app.include_router(audio.public_router, prefix="/audio", tags=["audio"])
app.include_router(quiz.router, prefix="/courses/{course_id}/quizzes", tags=["quizzes"])

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
