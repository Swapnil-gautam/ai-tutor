"""Hybrid search: BM25 + vector similarity with RRF fusion and cross-encoder reranking."""

from __future__ import annotations

import logging
import re

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from scholera.config import settings
from scholera.storage import metadata_db as db
from scholera.storage import vector_store

logger = logging.getLogger(__name__)

_reranker: CrossEncoder | None = None


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(settings.reranker_model)
    return _reranker


def hybrid_retrieve(
    course_id: str,
    query: str,
    top_k: int | None = None,
    lecture_numbers: list[int] | None = None,
) -> list[dict]:
    """
    Full retrieval pipeline:
    1. Parse query for metadata hints
    2. BM25 search
    3. Vector search
    4. RRF fusion
    5. Cross-lecture summary injection
    6. Cross-encoder reranking

    When ``lecture_numbers`` is set, retrieval is restricted to those lectures
    (slides + lecture summaries from those lectures only).
    """
    if top_k is None:
        top_k = settings.rerank_top_k

    lecture_scope: list[int] | None = None
    if lecture_numbers:
        scope: list[int] = []
        for x in lecture_numbers:
            try:
                v = int(x)
                if v > 0:
                    scope.append(v)
            except (TypeError, ValueError):
                pass
        lecture_scope = sorted(set(scope)) or None

    metadata_filter = _parse_query_metadata(query)
    if lecture_scope:
        metadata_filter = dict(metadata_filter) if metadata_filter else {}
        metadata_filter.pop("lecture_number", None)
        metadata_filter["lecture_numbers"] = lecture_scope

    all_chunks = db.get_chunks_for_course(course_id, chunk_type="slide")
    if not all_chunks:
        return []

    # --- BM25 (apply same metadata filter so both pipelines are aligned) ---
    bm25_pool = all_chunks
    if metadata_filter:
        filtered = _filter_chunks(all_chunks, metadata_filter)
        if filtered:
            bm25_pool = filtered
    bm25_results = _bm25_search(query, bm25_pool, settings.bm25_top_k)

    # --- Vector (build Chroma-compatible where clause) ---
    chroma_filter = _build_chroma_filter(metadata_filter) if metadata_filter else None
    vector_results = vector_store.query_vectors(
        course_id, query, settings.vector_top_k, chroma_filter,
    )

    # --- RRF Fusion ---
    fused = _rrf_fusion(bm25_results, vector_results, k=settings.rrf_k)

    # --- Inject summaries for cross-lecture queries ---
    if _is_cross_lecture_query(query):
        summaries = db.get_chunks_for_course(course_id, chunk_type="lecture_summary")
        topic_summaries = db.get_chunks_for_course(course_id, chunk_type="topic_summary")
        if lecture_scope:
            allowed = set(lecture_scope)
            extra_pool = [s for s in summaries if s.get("lecture_number") in allowed]
        else:
            extra_pool = summaries + topic_summaries
        for s in extra_pool:
            if s["id"] not in {r["id"] for r in fused}:
                fused.append({"id": s["id"], "text": s["combined_text"],
                              "metadata": s, "score": 0.3})

    # --- Reranker ---
    if len(fused) > top_k:
        fused = _rerank(query, fused, top_k)
    else:
        fused = sorted(fused, key=lambda x: x.get("score", 0), reverse=True)

    return fused[:top_k]


def _bm25_search(query: str, chunks: list[dict], top_k: int) -> list[dict]:
    corpus = [c["combined_text"] for c in chunks]
    tokenized_corpus = [doc.lower().split() for doc in corpus]
    tokenized_query = query.lower().split()

    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(tokenized_query)

    scored = list(zip(chunks, scores))
    scored.sort(key=lambda x: x[1], reverse=True)

    results = []
    for chunk, score in scored[:top_k]:
        results.append({
            "id": chunk["id"],
            "text": chunk["combined_text"],
            "metadata": chunk,
            "score": float(score),
        })
    return results


def _rrf_fusion(
    bm25_results: list[dict], vector_results: list[dict], k: int = 60
) -> list[dict]:
    """Reciprocal Rank Fusion to merge two ranked lists."""
    scores: dict[str, float] = {}
    docs: dict[str, dict] = {}

    for rank, doc in enumerate(bm25_results):
        doc_id = doc["id"]
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
        docs[doc_id] = doc

    for rank, doc in enumerate(vector_results):
        doc_id = doc["id"]
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
        docs[doc_id] = doc

    fused = []
    for doc_id, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        entry = docs[doc_id].copy()
        entry["score"] = score
        fused.append(entry)

    return fused


def _rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    reranker = _get_reranker()
    pairs = [(query, c["text"]) for c in candidates]
    scores = reranker.predict(pairs)

    for i, s in enumerate(scores):
        candidates[i]["rerank_score"] = float(s)

    candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
    return candidates[:top_k]


def _parse_query_metadata(query: str) -> dict | None:
    """Extract lecture number and/or slide/page number references from the query."""
    result: dict = {}

    lecture_patterns = [
        r"(?:lecture|week|lec)\s*#?\s*(\d+)",
    ]
    for pattern in lecture_patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            result["lecture_number"] = int(match.group(1))
            break

    slide_patterns = [
        r"(?:slide|page)\s*#?\s*(\d+)",
    ]
    for pattern in slide_patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            result["page_number"] = int(match.group(1))
            break

    return result or None


def _filter_chunks(chunks: list[dict], metadata_filter: dict) -> list[dict]:
    """Filter SQLite chunk rows by metadata (lecture_number(s), page_number)."""
    filtered = chunks
    if "lecture_numbers" in metadata_filter:
        allowed = set(metadata_filter["lecture_numbers"])
        filtered = [c for c in filtered if c.get("lecture_number") in allowed]
    elif "lecture_number" in metadata_filter:
        ln = metadata_filter["lecture_number"]
        filtered = [c for c in filtered if c.get("lecture_number") == ln]
    if "page_number" in metadata_filter:
        pn = metadata_filter["page_number"]
        filtered = [c for c in filtered if c.get("page_number") == pn]
    return filtered


def _build_chroma_filter(metadata_filter: dict) -> dict:
    """Convert parsed metadata into a Chroma-compatible where clause."""
    parts: list[dict] = []
    if "lecture_numbers" in metadata_filter:
        nums = metadata_filter["lecture_numbers"]
        if len(nums) == 1:
            parts.append({"lecture_number": nums[0]})
        else:
            parts.append({"$or": [{"lecture_number": n} for n in nums]})
    elif "lecture_number" in metadata_filter:
        parts.append({"lecture_number": metadata_filter["lecture_number"]})
    if "page_number" in metadata_filter:
        parts.append({"page_number": metadata_filter["page_number"]})

    if len(parts) == 1:
        return parts[0]
    if len(parts) > 1:
        return {"$and": parts}
    return {}


def _is_cross_lecture_query(query: str) -> bool:
    cross_indicators = [
        "relate", "connect", "across", "compare", "between",
        "all lectures", "everything", "entire course", "overall",
        "week.*and.*week", "lecture.*and.*lecture",
    ]
    query_lower = query.lower()
    return any(re.search(indicator, query_lower) for indicator in cross_indicators)
