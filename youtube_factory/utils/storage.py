import os
from pathlib import Path

def get_storage_path() -> Path:
    """
    Returns the base storage path from environment or default.
    Ensures the directory exists.
    """
    path_str = os.environ.get("STORAGE_PATH", "./media")
    path = Path(path_str).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_job_storage_path(job_id: int) -> Path:
    """
    Returns the storage path for a specific job.
    """
    base = get_storage_path()
    job_path = base / str(job_id)
    job_path.mkdir(parents=True, exist_ok=True)
    return job_path
