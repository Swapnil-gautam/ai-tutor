from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"
    gemini_tts_voice: str = "charon"
    gemini_tts_language: str = "en-US"

    embedding_model: str = "all-MiniLM-L6-v2"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    data_dir: Path = Path("data")
    chroma_dir: Path = Path("data/chroma")
    uploads_dir: Path = Path("data/uploads")
    images_dir: Path = Path("data/images")
    audio_dir: Path = Path("data/audio")
    sqlite_path: Path = Path("data/scholera.db")

    # Ingestion
    text_density_threshold: int = 80
    max_chunk_tokens: int = 1000
    chunk_overlap_tokens: int = 100

    # Retrieval
    bm25_top_k: int = 20
    vector_top_k: int = 20
    rerank_top_k: int = 8
    rrf_k: int = 60

    model_config = {"env_file": ".env", "env_prefix": "SCHOLERA_"}


settings = Settings()

for d in [settings.data_dir, settings.chroma_dir, settings.uploads_dir, settings.images_dir, settings.audio_dir]:
    d.mkdir(parents=True, exist_ok=True)
