"""CLI entry points for Scholera: run server, ingest files, ask questions, run evaluation."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from scholera.storage.metadata_db import init_db


def main():
    parser = argparse.ArgumentParser(description="Scholera AI Backend")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- serve ---
    serve_cmd = sub.add_parser("serve", help="Start the API server")
    serve_cmd.add_argument("--host", default="0.0.0.0")
    serve_cmd.add_argument("--port", type=int, default=8000)

    # --- ingest ---
    ingest_cmd = sub.add_parser("ingest", help="Ingest a file into a course")
    ingest_cmd.add_argument("--course-id", required=True)
    ingest_cmd.add_argument("--file", required=True)
    ingest_cmd.add_argument("--lecture-number", type=int, default=None)
    ingest_cmd.add_argument("--lecture-title", default="")

    # --- ask ---
    ask_cmd = sub.add_parser("ask", help="Ask the AI tutor a question (RAG + course materials)")
    ask_cmd.add_argument("--course-id", required=True)
    ask_cmd.add_argument("question", nargs="+")

    # --- ask-raw: Gemini only, no RAG ---
    raw_cmd = sub.add_parser(
        "ask-raw",
        help="Ask Gemini directly with no course context or retrieval (baseline)",
    )
    raw_cmd.add_argument("question", nargs="+")
    raw_cmd.add_argument(
        "--system",
        default="",
        help="Optional instructions prepended (e.g. 'Answer concisely for a CS student.')",
    )

    # --- evaluate ---
    eval_cmd = sub.add_parser("evaluate", help="Run evaluation on a test set")
    eval_cmd.add_argument("--course-id", required=True)
    eval_cmd.add_argument("--test-set", required=True)
    eval_cmd.add_argument("--output", default=None)

    # --- create-course ---
    create_cmd = sub.add_parser("create-course", help="Create a new course")
    create_cmd.add_argument("--title", required=True)
    create_cmd.add_argument("--description", default="")

    # --- reset-db ---
    sub.add_parser(
        "reset-db",
        help="Delete ALL local data stores (SQLite + Chroma + uploads/images/audio)",
    )

    args = parser.parse_args()
    init_db()

    if args.command == "serve":
        _run_server(args)
    elif args.command == "ingest":
        _run_ingest(args)
    elif args.command == "ask-raw":
        _run_ask_raw(args)
    elif args.command == "ask":
        asyncio.run(_run_ask(args))
    elif args.command == "evaluate":
        asyncio.run(_run_evaluate(args))
    elif args.command == "create-course":
        _run_create_course(args)
    elif args.command == "reset-db":
        _run_reset_db(args)


def _run_server(args):
    import uvicorn
    uvicorn.run("scholera.api.main:app", host=args.host, port=args.port, reload=True)


def _run_ingest(args):
    from scholera.ingestion.pipeline import run_ingestion
    from scholera.storage import metadata_db as db

    course = db.get_course(args.course_id)
    if not course:
        print(f"Error: Course '{args.course_id}' not found.")
        sys.exit(1)

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File '{file_path}' not found.")
        sys.exit(1)

    ext = file_path.suffix.lower()
    material = db.create_material(
        course_id=args.course_id,
        filename=file_path.name,
        file_type=ext.lstrip("."),
        lecture_number=args.lecture_number,
        lecture_title=args.lecture_title,
    )

    import shutil
    from scholera.config import settings
    upload_path = settings.uploads_dir / f"{material['id']}{ext}"
    shutil.copy2(str(file_path), str(upload_path))

    print(f"Ingesting {file_path.name} (material_id={material['id']})...")
    run_ingestion(material["id"], str(upload_path))
    print("Ingestion complete.")


def _run_ask_raw(args):
    from scholera.generation.api_errors import format_client_error
    from scholera.generation.direct_gemini import ask_gemini_direct

    question = " ".join(args.question)
    print(f"\nQuestion (no RAG): {question}\n")

    try:
        answer = ask_gemini_direct(
            question,
            system_instruction=args.system or None,
        )
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        friendly = format_client_error(e)
        if friendly:
            print(friendly)
        else:
            print(f"Error: {e}")
        sys.exit(1)

    print("=" * 60)
    print("ANSWER (Gemini only):")
    print("=" * 60)
    print(answer)


async def _run_ask(args):
    from scholera.generation.tutor import ask_tutor
    from scholera.storage import metadata_db as db

    course = db.get_course(args.course_id)
    if not course:
        print(f"Error: Course '{args.course_id}' not found.")
        sys.exit(1)

    question = " ".join(args.question)
    print(f"\nQuestion: {question}\n")

    result = await ask_tutor(args.course_id, course["title"], question)

    print("=" * 60)
    print("ANSWER:")
    print("=" * 60)
    print(result["answer"])
    print("\n" + "-" * 60)
    print(f"Sources ({result['chunks_retrieved']} chunks retrieved):")
    for src in result["sources"]:
        print(f"  - Lecture {src['lecture_number']}, Slide {src['page_number']} ({src['source_file']})")


async def _run_evaluate(args):
    from scholera.evaluation.eval_runner import run_evaluation
    from scholera.storage import metadata_db as db

    course = db.get_course(args.course_id)
    if not course:
        print(f"Error: Course '{args.course_id}' not found.")
        sys.exit(1)

    print(f"Running evaluation with test set: {args.test_set}")
    report = await run_evaluation(
        args.course_id, course["title"], args.test_set, args.output,
    )

    print("\n" + "=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)
    metrics = report["metrics"]
    print(f"Total questions:    {metrics['total_questions']}")
    print(f"Retrieval Recall:   {metrics['retrieval_recall']:.1%}")
    print(f"Avg latency:        {metrics['avg_latency_seconds']:.2f}s")

    if "by_difficulty" in metrics:
        print("\nBy difficulty:")
        for diff, stats in metrics["by_difficulty"].items():
            print(f"  {diff}: {stats['count']} questions, recall={stats['retrieval_recall']:.1%}")

    if "by_type" in metrics:
        print("\nBy type:")
        for qtype, stats in metrics["by_type"].items():
            print(f"  {qtype}: {stats['count']} questions, recall={stats['retrieval_recall']:.1%}")


def _run_create_course(args):
    from scholera.storage import metadata_db as db
    course = db.create_course(args.title, args.description)
    print(f"Course created: {course['id']} — {course['title']}")


def _run_reset_db(args):
    from scholera.storage.reset_db import reset_all_local_data
    reset_all_local_data()
    init_db()
    print("Local storage cleared (SQLite + Chroma + uploads/images/audio).")


if __name__ == "__main__":
    main()
