from __future__ import annotations

import chromadb
from sentence_transformers import SentenceTransformer

from scholera.config import settings

_client: chromadb.PersistentClient | None = None
_embed_model: SentenceTransformer | None = None


def _get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    return _client


def get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer(settings.embedding_model)
    return _embed_model


def get_collection(course_id: str) -> chromadb.Collection:
    return _get_client().get_or_create_collection(
        name=f"course_{course_id}",
        metadata={"hnsw:space": "cosine"},
    )


_CHROMA_MAX_BATCH = 5_000


def add_chunks(course_id: str, chunks: list[dict]):
    collection = get_collection(course_id)
    model = get_embed_model()

    texts = [c["combined_text"] for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=False).tolist()

    for start in range(0, len(chunks), _CHROMA_MAX_BATCH):
        end = start + _CHROMA_MAX_BATCH
        batch = chunks[start:end]
        collection.add(
            ids=[c["id"] for c in batch],
            embeddings=embeddings[start:end],
            documents=texts[start:end],
            metadatas=[
                {
                    "material_id": c["material_id"],
                    "lecture_number": c.get("lecture_number") or 0,
                    "lecture_title": c.get("lecture_title", ""),
                    "page_number": c.get("page_number") or 0,
                    "chunk_type": c["chunk_type"],
                    "source_file": c.get("source_file", ""),
                }
                for c in batch
            ],
        )


def query_vectors(
    course_id: str, query_text: str, top_k: int = 20,
    where_filter: dict | None = None,
) -> list[dict]:
    collection = get_collection(course_id)
    model = get_embed_model()

    query_embedding = model.encode([query_text]).tolist()

    kwargs: dict = {
        "query_embeddings": query_embedding,
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if where_filter:
        kwargs["where"] = where_filter

    results = collection.query(**kwargs)

    hits = []
    for i in range(len(results["ids"][0])):
        hits.append({
            "id": results["ids"][0][i],
            "text": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
        })
    return hits
