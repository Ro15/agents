"""
File storage layer — saves uploaded files locally as archives.
Files are stored under  backend/uploads/{dataset_id}/{filename}
"""

import logging
import os
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Project-local upload directory (relative to backend/)
_BACKEND_DIR = Path(__file__).resolve().parent.parent          # …/backend
UPLOAD_DIR = _BACKEND_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def save_file(dataset_id: str, filename: str, content: bytes) -> Path:
    """Save an uploaded file and return the full path."""
    dest_dir = UPLOAD_DIR / dataset_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename
    dest_path.write_bytes(content)
    logger.info(f"Archived file → {dest_path}  ({len(content)} bytes)")
    return dest_path


def get_file_path(dataset_id: str, filename: str) -> Optional[Path]:
    """Return the path to a previously-saved file, or None."""
    p = UPLOAD_DIR / dataset_id / filename
    return p if p.exists() else None


def list_files(dataset_id: str) -> List[Path]:
    """List all archived files for a dataset."""
    d = UPLOAD_DIR / dataset_id
    return sorted(d.iterdir()) if d.is_dir() else []


def delete_files(dataset_id: str) -> int:
    """Delete all archived files for a dataset.  Returns count deleted."""
    import shutil
    d = UPLOAD_DIR / dataset_id
    if not d.is_dir():
        return 0
    count = sum(1 for _ in d.iterdir())
    shutil.rmtree(d)
    return count
