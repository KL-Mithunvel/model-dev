"""Single place that decides where data lives on disk (never build these paths by hand)."""

from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def data_dir(config: dict[str, Any]) -> Path:
    """Return the absolute data directory; a relative ``app.data_dir`` is under the repo root."""
    configured = Path(config["app"]["data_dir"])
    return configured if configured.is_absolute() else REPO_ROOT / configured


def db_path(config: dict[str, Any]) -> Path:
    """Return the SQLite database file path."""
    return data_dir(config) / config["database"]["filename"]


def project_dir(config: dict[str, Any], project_id: int) -> Path:
    """Return the folder that holds one project's files."""
    return data_dir(config) / "projects" / str(int(project_id))


def images_dir(config: dict[str, Any], project_id: int) -> Path:
    """Return the folder with the project's stored (copied) original images."""
    return project_dir(config, project_id) / "images"


def thumbs_dir(config: dict[str, Any], project_id: int) -> Path:
    """Return the folder with the project's thumbnails."""
    return project_dir(config, project_id) / "thumbs"
