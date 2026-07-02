from __future__ import annotations

import shutil

from scholera.config import settings


def reset_all_local_data() -> None:
    """
    Clears ALL local persisted state:
    - SQLite file (plus WAL/SHM sidecars)
    - Chroma persistent directory
    - Uploads / rendered images / generated audio directories
    """

    # --- SQLite ---
    db_path = settings.sqlite_path
    for p in (db_path, db_path.with_suffix(db_path.suffix + "-wal"), db_path.with_suffix(db_path.suffix + "-shm")):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            # Best-effort cleanup; file may be locked if server is running.
            pass

    # --- Chroma + local artifacts ---
    for d in (settings.chroma_dir, settings.uploads_dir, settings.images_dir, settings.audio_dir):
        try:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass

    # Recreate base dirs for subsequent runs
    for d in (settings.data_dir, settings.chroma_dir, settings.uploads_dir, settings.images_dir, settings.audio_dir):
        d.mkdir(parents=True, exist_ok=True)

