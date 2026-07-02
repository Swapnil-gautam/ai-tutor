from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from scholera.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id),
    filename TEXT NOT NULL,
    lecture_number INTEGER,
    lecture_title TEXT DEFAULT '',
    file_type TEXT NOT NULL,
    page_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    course_id TEXT REFERENCES courses(id),
    title TEXT DEFAULT 'New Chat',
    mode TEXT DEFAULT 'rag',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quizzes (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id),
    title TEXT NOT NULL,
    lecture_number INTEGER,
    lecture_numbers_json TEXT DEFAULT NULL,
    topic TEXT DEFAULT '',
    num_questions INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_questions (
    id TEXT PRIMARY KEY,
    quiz_id TEXT NOT NULL REFERENCES quizzes(id),
    question_text TEXT NOT NULL,
    option_a TEXT NOT NULL,
    option_b TEXT NOT NULL,
    option_c TEXT NOT NULL,
    option_d TEXT NOT NULL,
    correct_option TEXT NOT NULL,
    explanation TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id),
    material_id TEXT NOT NULL REFERENCES materials(id),
    lecture_number INTEGER,
    lecture_title TEXT DEFAULT '',
    page_number INTEGER,
    chunk_type TEXT NOT NULL DEFAULT 'slide',
    text_content TEXT DEFAULT '',
    visual_description TEXT DEFAULT '',
    combined_text TEXT DEFAULT '',
    topics TEXT DEFAULT '[]',
    has_equations INTEGER DEFAULT 0,
    has_images INTEGER DEFAULT 0,
    source_file TEXT DEFAULT ''
);
"""


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Apply schema if missing (e.g. new empty file after DB was deleted while server ran)."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='courses' LIMIT 1",
    ).fetchone()
    if row is None:
        conn.executescript(_SCHEMA)
    _ensure_quiz_migrations(conn)


def _ensure_quiz_migrations(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='quizzes' LIMIT 1",
    ).fetchone()
    if row is None:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(quizzes)").fetchall()}
    if "lecture_numbers_json" not in cols:
        conn.execute(
            "ALTER TABLE quizzes ADD COLUMN lecture_numbers_json TEXT DEFAULT NULL",
        )


def init_db():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.sqlite_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_tables(conn)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _connect():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.sqlite_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_tables(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    if "topics" in d:
        d["topics"] = json.loads(d["topics"])
    for bool_field in ("has_equations", "has_images"):
        if bool_field in d:
            d[bool_field] = bool(d[bool_field])
    return d


# ---- Courses ----

def create_course(title: str, description: str = "") -> dict:
    cid = _new_id()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO courses (id, title, description, created_at) VALUES (?, ?, ?, ?)",
            (cid, title, description, _now()),
        )
    return get_course(cid)


def get_course(course_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    return _row_to_dict(row)


def list_courses() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM courses ORDER BY created_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


# ---- Materials ----

def create_material(
    course_id: str, filename: str, file_type: str,
    lecture_number: int | None = None, lecture_title: str = "",
) -> dict:
    mid = _new_id()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO materials (id, course_id, filename, lecture_number, lecture_title, file_type, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (mid, course_id, filename, lecture_number, lecture_title, file_type, _now()),
        )
    return get_material(mid)


def get_material(material_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
    return _row_to_dict(row)


def list_materials(course_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM materials WHERE course_id = ? ORDER BY lecture_number, created_at",
            (course_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_material_progress(material_id: str, status: str, progress_step: str = "", progress_pct: int = 0):
    """Update material status with progress detail visible to the UI."""
    with _connect() as conn:
        conn.execute(
            "UPDATE materials SET status = ? WHERE id = ?",
            (f"{status}|{progress_step}|{progress_pct}", material_id),
        )


def get_material_progress(material_id: str) -> dict:
    mat = get_material(material_id)
    if not mat:
        return {"status": "unknown", "step": "", "progress": 0}
    raw = mat.get("status", "pending")
    parts = raw.split("|", 2)
    return {
        "status": parts[0],
        "step": parts[1] if len(parts) > 1 else "",
        "progress": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
    }


def delete_material(material_id: str):
    with _connect() as conn:
        conn.execute("DELETE FROM chunks WHERE material_id = ?", (material_id,))
        conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))


def update_material(material_id: str, **fields) -> dict | None:
    if not fields:
        return get_material(material_id)
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [material_id]
    with _connect() as conn:
        conn.execute(f"UPDATE materials SET {set_clause} WHERE id = ?", values)
    return get_material(material_id)


# ---- Chunks ----

def insert_chunks(chunks: list[dict]):
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO chunks (id, course_id, material_id, lecture_number, lecture_title, "
            "page_number, chunk_type, text_content, visual_description, combined_text, "
            "topics, has_equations, has_images, source_file) "
            "VALUES (:id, :course_id, :material_id, :lecture_number, :lecture_title, "
            ":page_number, :chunk_type, :text_content, :visual_description, :combined_text, "
            ":topics, :has_equations, :has_images, :source_file)",
            [
                {
                    **c,
                    "topics": json.dumps(c.get("topics", [])),
                    "has_equations": int(c.get("has_equations", False)),
                    "has_images": int(c.get("has_images", False)),
                }
                for c in chunks
            ],
        )


def get_chunks_for_course(course_id: str, chunk_type: str | None = None) -> list[dict]:
    with _connect() as conn:
        if chunk_type:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE course_id = ? AND chunk_type = ? ORDER BY lecture_number, page_number",
                (course_id, chunk_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE course_id = ? ORDER BY lecture_number, page_number",
                (course_id,),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_chunks_for_material(material_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chunks WHERE material_id = ? ORDER BY page_number",
            (material_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ---- Chat Sessions ----

def create_chat_session(course_id: str | None, mode: str = "rag", title: str = "New Chat") -> dict:
    sid = _new_id()
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO chat_sessions (id, course_id, title, mode, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, course_id, title, mode, now, now),
        )
    return get_chat_session(sid)


def get_chat_session(session_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    return _row_to_dict(row)


def list_chat_sessions(course_id: str | None = None) -> list[dict]:
    with _connect() as conn:
        if course_id:
            rows = conn.execute(
                "SELECT * FROM chat_sessions WHERE course_id = ? ORDER BY updated_at DESC",
                (course_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chat_sessions ORDER BY updated_at DESC"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_chat_session(session_id: str, **fields) -> dict | None:
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [session_id]
    with _connect() as conn:
        conn.execute(f"UPDATE chat_sessions SET {set_clause} WHERE id = ?", values)
    return get_chat_session(session_id)


def delete_chat_session(session_id: str):
    with _connect() as conn:
        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))


# ---- Chat Messages ----

def add_chat_message(session_id: str, role: str, content: str, sources: list | None = None) -> dict:
    mid = _new_id()
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO chat_messages (id, session_id, role, content, sources, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (mid, session_id, role, content, json.dumps(sources or []), now),
        )
        conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (now, session_id))
    return {"id": mid, "session_id": session_id, "role": role, "content": content,
            "sources": sources or [], "created_at": now}


def get_chat_messages(session_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d["sources"])
        result.append(d)
    return result


# ---- Quizzes ----

def _enrich_quiz_row(d: dict) -> dict:
    """Add lecture_numbers list for API/UI from JSON + legacy lecture_number."""
    nums: list[int] = []
    raw = d.get("lecture_numbers_json")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for x in parsed:
                    try:
                        v = int(x)
                        if v > 0:
                            nums.append(v)
                    except (TypeError, ValueError):
                        pass
                nums = sorted(set(nums))
        except (json.JSONDecodeError, TypeError, ValueError):
            nums = []
    if not nums and d.get("lecture_number") is not None:
        nums = [int(d["lecture_number"])]
    d["lecture_numbers"] = nums
    return d


def create_quiz(
    course_id: str,
    title: str,
    lecture_number: int | None = None,
    topic: str = "",
    questions: list[dict] | None = None,
    lecture_numbers: list[int] | None = None,
) -> dict:
    qid = _new_id()
    now = _now()
    nums = []
    for x in lecture_numbers or []:
        try:
            v = int(x)
            if v > 0:
                nums.append(v)
        except (TypeError, ValueError):
            pass
    nums = sorted(set(nums))
    ln_db = nums[0] if len(nums) == 1 else None
    ln_json = json.dumps(nums) if nums else None
    if not nums and lecture_number is not None:
        ln_db = int(lecture_number)
        ln_json = json.dumps([ln_db])

    with _connect() as conn:
        conn.execute(
            "INSERT INTO quizzes (id, course_id, title, lecture_number, lecture_numbers_json, "
            "topic, num_questions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (qid, course_id, title, ln_db, ln_json, topic, len(questions or []), now),
        )
        if questions:
            for i, q in enumerate(questions):
                conn.execute(
                    "INSERT INTO quiz_questions "
                    "(id, quiz_id, question_text, option_a, option_b, option_c, option_d, "
                    "correct_option, explanation, sort_order) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (_new_id(), qid, q["question_text"], q["option_a"], q["option_b"],
                     q["option_c"], q["option_d"], q["correct_option"],
                     q.get("explanation", ""), i),
                )
    return get_quiz(qid)


def get_quiz(quiz_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()
    d = _row_to_dict(row)
    return _enrich_quiz_row(d) if d else None


def list_quizzes(course_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM quizzes WHERE course_id = ? ORDER BY created_at DESC",
            (course_id,),
        ).fetchall()
    return [_enrich_quiz_row(_row_to_dict(r)) for r in rows]


def get_quiz_questions(quiz_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM quiz_questions WHERE quiz_id = ? ORDER BY sort_order",
            (quiz_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_quiz(quiz_id: str):
    with _connect() as conn:
        conn.execute("DELETE FROM quiz_questions WHERE quiz_id = ?", (quiz_id,))
        conn.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))


# ---- Stats ----

def get_course_stats(course_id: str) -> dict:
    with _connect() as conn:
        mat_count = conn.execute(
            "SELECT COUNT(*) FROM materials WHERE course_id = ?", (course_id,)
        ).fetchone()[0]
        total_pages = conn.execute(
            "SELECT COALESCE(SUM(page_count), 0) FROM materials WHERE course_id = ?", (course_id,)
        ).fetchone()[0]
        chunk_count = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE course_id = ? AND chunk_type = 'slide'", (course_id,)
        ).fetchone()[0]
        summary_count = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE course_id = ? AND chunk_type IN ('lecture_summary', 'topic_summary')",
            (course_id,),
        ).fetchone()[0]
    return {
        "course_id": course_id,
        "materials": mat_count,
        "total_pages": total_pages,
        "chunks": chunk_count,
        "summaries": summary_count,
    }
