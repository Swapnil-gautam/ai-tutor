"""Evaluation harness: run test questions against the system and compute metrics."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from scholera.generation.tutor import ask_tutor
from scholera.retrieval.hybrid_search import hybrid_retrieve

logger = logging.getLogger(__name__)


async def run_evaluation(
    course_id: str,
    course_title: str,
    test_set_path: str,
    output_path: str | None = None,
) -> dict:
    """
    Run a test set against the tutor and compute metrics.

    Test set format (JSON):
    [
        {
            "question": str,
            "expected_answer": str,
            "source_lecture": int | null,
            "difficulty": "easy" | "medium" | "hard",
            "topics": [str],
            "type": "factual" | "conceptual" | "cross_lecture"
        }
    ]
    """
    test_set = json.loads(Path(test_set_path).read_text(encoding="utf-8"))
    results = []
    total_latency = 0.0

    for i, test_case in enumerate(test_set):
        question = test_case["question"]
        logger.info("Evaluating question %d/%d: %s", i + 1, len(test_set), question[:80])

        start = time.time()
        retrieved = hybrid_retrieve(course_id, question)
        retrieval_time = time.time() - start

        start = time.time()
        response = await ask_tutor(course_id, course_title, question)
        total_time = retrieval_time + (time.time() - start)
        total_latency += total_time

        retrieval_hit = _check_retrieval_hit(
            retrieved, test_case.get("source_lecture")
        )

        result = {
            "question": question,
            "expected_answer": test_case.get("expected_answer", ""),
            "actual_answer": response["answer"],
            "sources": response["sources"],
            "chunks_retrieved": response["chunks_retrieved"],
            "retrieval_hit": retrieval_hit,
            "latency_seconds": round(total_time, 2),
            "difficulty": test_case.get("difficulty", "unknown"),
            "question_type": test_case.get("type", "unknown"),
        }
        results.append(result)

    metrics = _compute_metrics(results)
    metrics["total_questions"] = len(test_set)
    metrics["avg_latency_seconds"] = round(total_latency / max(len(test_set), 1), 2)

    report = {"metrics": metrics, "results": results}

    if output_path:
        Path(output_path).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Evaluation report saved to %s", output_path)

    return report


def _check_retrieval_hit(retrieved: list[dict], expected_lecture: int | None) -> bool:
    """Check if the expected source lecture appears in the retrieved chunks."""
    if expected_lecture is None:
        return True
    for chunk in retrieved:
        meta = chunk.get("metadata", {})
        if meta.get("lecture_number") == expected_lecture:
            return True
    return False


def _compute_metrics(results: list[dict]) -> dict:
    if not results:
        return {}

    total = len(results)
    retrieval_hits = sum(1 for r in results if r["retrieval_hit"])

    by_type: dict[str, list] = {}
    by_difficulty: dict[str, list] = {}
    for r in results:
        by_type.setdefault(r["question_type"], []).append(r)
        by_difficulty.setdefault(r["difficulty"], []).append(r)

    return {
        "retrieval_recall": round(retrieval_hits / total, 3),
        "retrieval_hits": retrieval_hits,
        "by_type": {
            qtype: {
                "count": len(qs),
                "retrieval_recall": round(
                    sum(1 for q in qs if q["retrieval_hit"]) / len(qs), 3
                ),
            }
            for qtype, qs in by_type.items()
        },
        "by_difficulty": {
            diff: {
                "count": len(qs),
                "retrieval_recall": round(
                    sum(1 for q in qs if q["retrieval_hit"]) / len(qs), 3
                ),
            }
            for diff, qs in by_difficulty.items()
        },
    }
