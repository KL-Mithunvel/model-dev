"""Import images from a folder or a zip into a project.

For every candidate file the importer: checks extension and size, skips content duplicates
(SHA-256, per project), validates and decodes the image with Pillow, applies EXIF orientation,
copies the original into the project's images folder, and writes a thumbnail. Nothing is skipped
silently: every outcome is counted and non-trivial problems are recorded on the batch.

Stored ``width``/``height`` are the EXIF-oriented dimensions, i.e. what a browser displays.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from studio import paths
from studio.db import utc_now

_CHUNK = 1024 * 1024
_BYTES_PER_MB = 1024 * 1024
_BYTES_PER_GB = 1024**3

ProgressCallback = Callable[[int, int, "ImportReport"], None]


class ImportFailed(Exception):
    """The whole import cannot proceed (bad source, unknown project, unsafe or oversized zip)."""


@dataclass
class ImportReport:
    """Outcome of one import run. Counts are exact; ``problems`` is capped (see config)."""

    batch_id: int
    added: int = 0
    duplicates: int = 0
    corrupt: int = 0
    oversize: int = 0
    unsupported: int = 0
    problems: list[dict[str, str]] = field(default_factory=list)
    problems_dropped: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "added": self.added,
            "duplicates": self.duplicates,
            "corrupt": self.corrupt,
            "oversize": self.oversize,
            "unsupported": self.unsupported,
            "problems": self.problems,
            "problems_dropped": self.problems_dropped,
        }


def sha256_of(path: Path) -> str:
    """Return the hex SHA-256 of a file's bytes, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def list_candidate_files(root: Path) -> list[Path]:
    """Return every regular file under ``root`` (symlinks are not followed), sorted."""
    found: list[Path] = []
    for folder, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            candidate = Path(folder) / name
            if candidate.is_symlink():
                continue
            found.append(candidate)
    return sorted(found)


def _safe_extract(zip_path: Path, destination: Path, max_bytes: int, report_problem) -> None:
    """Extract ``zip_path`` into ``destination`` with zip-slip and zip-bomb protection."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as error:
        raise ImportFailed(f"Not a readable zip file: {zip_path.name} ({error})") from error
    with archive:
        members = archive.infolist()
        total = sum(member.file_size for member in members)
        if total > max_bytes:
            raise ImportFailed(
                f"Zip would expand to {total / _BYTES_PER_GB:.2f} GB, above the "
                f"{max_bytes / _BYTES_PER_GB:.2f} GB limit (importing.max_zip_uncompressed_gb)."
            )
        root = destination.resolve()
        for member in members:
            if member.is_dir():
                continue
            target = (destination / member.filename).resolve()
            is_symlink = (member.external_attr >> 16) & 0o170000 == 0o120000
            if root not in target.parents or is_symlink:
                report_problem(member.filename, "unsafe path or link inside zip; skipped")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink, _CHUNK)


def _make_thumbnail(image: Image.Image, size: int) -> Image.Image:
    thumb = image.copy()
    thumb.thumbnail((size, size))
    if thumb.mode not in ("RGB", "L"):
        thumb = thumb.convert("RGB")
    return thumb


def _classify_and_store(
    path: Path, config: dict[str, Any], project_id: int, sha: str
) -> tuple[str, dict[str, Any] | str]:
    """Validate one image and write its files.

    Returns ``("ok", info)`` or ``(outcome, reason)`` where outcome is ``"corrupt"`` or
    ``"oversize"``.
    """
    limits = config["images"]
    try:
        with Image.open(path) as probe:
            raw_width, raw_height = probe.size
            if max(raw_width, raw_height) > limits["max_side_px"]:
                return "oversize", f"{raw_width}x{raw_height} exceeds {limits['max_side_px']} px"
            probe.verify()  # structural check; the file must be reopened afterwards
        with Image.open(path) as image:
            image.load()
            oriented = ImageOps.exif_transpose(image)
            width, height = oriented.size
            thumb = _make_thumbnail(oriented, limits["thumbnail_px"])
    except Image.DecompressionBombError as error:
        return "oversize", str(error)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError) as error:
        return "corrupt", f"{type(error).__name__}: {error}"

    extension = path.suffix.lower()
    stored_name = f"{sha}{extension}"
    images_folder = paths.images_dir(config, project_id)
    thumbs_folder = paths.thumbs_dir(config, project_id)
    images_folder.mkdir(parents=True, exist_ok=True)
    thumbs_folder.mkdir(parents=True, exist_ok=True)
    thumb.save(thumbs_folder / f"{sha}.jpg", format="JPEG", quality=85)
    shutil.copy2(path, images_folder / stored_name)
    return "ok", {
        "stored_name": stored_name,
        "width": width,
        "height": height,
        "bytes": path.stat().st_size,
    }


def _run(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    project_id: int,
    files: list[Path],
    display_root: Path,
    batch_id: int,
    progress: ProgressCallback | None,
) -> ImportReport:
    report = ImportReport(batch_id=batch_id)
    allowed = {ext.lower() for ext in config["images"]["allowed_extensions"]}
    max_bytes = int(config["images"]["max_file_mb"] * _BYTES_PER_MB)
    max_problems = config["importing"]["max_problems_recorded"]
    every = max(1, int(config["importing"]["progress_every"]))

    def add_problem(name: str, reason: str) -> None:
        if len(report.problems) < max_problems:
            report.problems.append({"path": name, "reason": reason})
        else:
            report.problems_dropped += 1

    for index, path in enumerate(files, start=1):
        try:
            name = str(path.relative_to(display_root))
        except ValueError:
            name = path.name
        if path.suffix.lower() not in allowed:
            report.unsupported += 1
        elif path.stat().st_size > max_bytes:
            report.oversize += 1
            add_problem(name, f"larger than {config['images']['max_file_mb']} MB")
        else:
            sha = sha256_of(path)
            exists = conn.execute(
                "SELECT 1 FROM images WHERE project_id = ? AND sha256 = ?", (project_id, sha)
            ).fetchone()
            if exists:
                report.duplicates += 1
            else:
                outcome, detail = _classify_and_store(path, config, project_id, sha)
                if outcome == "ok":
                    conn.execute(
                        "INSERT INTO images (project_id, batch_id, sha256, stored_name,"
                        " original_name, width, height, bytes, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            project_id,
                            batch_id,
                            sha,
                            detail["stored_name"],
                            path.name,
                            detail["width"],
                            detail["height"],
                            detail["bytes"],
                            utc_now(),
                        ),
                    )
                    report.added += 1
                elif outcome == "oversize":
                    report.oversize += 1
                    add_problem(name, str(detail))
                else:
                    report.corrupt += 1
                    add_problem(name, str(detail))
        if index % every == 0:
            conn.commit()
            if progress:
                progress(index, len(files), report)
    conn.commit()
    if progress:
        progress(len(files), len(files), report)
    return report


def _write_batch(conn: sqlite3.Connection, report: ImportReport) -> None:
    conn.execute(
        "UPDATE batches SET added = ?, duplicates = ?, corrupt = ?, oversize = ?,"
        " unsupported = ?, problems = ? WHERE id = ?",
        (
            report.added,
            report.duplicates,
            report.corrupt,
            report.oversize,
            report.unsupported,
            json.dumps(report.problems),
            report.batch_id,
        ),
    )
    conn.commit()


def import_source(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    project_id: int,
    source: Path,
    progress: ProgressCallback | None = None,
) -> ImportReport:
    """Import a folder or a ``.zip`` into a project and return the report.

    Raises:
        ImportFailed: unknown project, missing/unsupported source, or an unsafe/oversized zip.
    """
    source = Path(source)
    if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise ImportFailed(f"Project {project_id} does not exist.")
    if not source.exists():
        raise ImportFailed(f"Source not found: {source}")
    is_zip = source.is_file() and source.suffix.lower() == ".zip"
    if not (source.is_dir() or is_zip):
        raise ImportFailed("Source must be a folder or a .zip file.")

    cursor = conn.execute(
        "INSERT INTO batches (project_id, source, created_at) VALUES (?, ?, ?)",
        (project_id, str(source), utc_now()),
    )
    conn.commit()
    report = ImportReport(batch_id=int(cursor.lastrowid))
    temp_root: Path | None = None
    try:
        if is_zip:
            scratch = paths.data_dir(config) / "tmp"
            scratch.mkdir(parents=True, exist_ok=True)
            temp_root = Path(tempfile.mkdtemp(prefix="import_", dir=scratch))
            unsafe: list[tuple[str, str]] = []
            max_zip = int(config["importing"]["max_zip_uncompressed_gb"] * _BYTES_PER_GB)
            _safe_extract(source, temp_root, max_zip, lambda n, r: unsafe.append((n, r)))
            files = list_candidate_files(temp_root)
            display_root = temp_root
        else:
            files = list_candidate_files(source)
            display_root = source
        report = _run(conn, config, project_id, files, display_root, report.batch_id, progress)
        if is_zip:
            max_problems = config["importing"]["max_problems_recorded"]
            for name, reason in unsafe:
                report.corrupt += 1
                if len(report.problems) < max_problems:
                    report.problems.append({"path": name, "reason": reason})
                else:
                    report.problems_dropped += 1
        return report
    finally:
        _write_batch(conn, report)
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)
