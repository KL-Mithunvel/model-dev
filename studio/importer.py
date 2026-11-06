"""Import images from a folder or a zip into a project.

For every candidate file the importer: checks extension and size, skips content duplicates
(SHA-256, per project), validates and decodes the image with Pillow, applies EXIF orientation,
copies the original into the project's images folder, and writes a thumbnail. Nothing is skipped
silently: every outcome is counted and non-trivial problems are recorded on the batch.

Stored ``width``/``height`` are the EXIF-oriented dimensions, i.e. what a browser displays.
"""

import hashlib
import io
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

_EXIF_ORIENTATION = 0x0112
_SWAPPING_ORIENTATIONS = {5, 6, 7, 8}  # EXIF orientations that rotate by 90 degrees (swap w/h)
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
    cancelled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "cancelled": self.cancelled,
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


def list_candidate_files(root: Path) -> tuple[list[Path], list[Path]]:
    """Return ``(files, skipped_links)`` under ``root``, both sorted.

    Symlinks and Windows junctions are never followed; the ones found are returned in
    ``skipped_links`` so the caller can report them instead of dropping them silently.
    """
    found: list[Path] = []
    skipped: list[Path] = []
    for folder, dirs, files in os.walk(root, followlinks=False):
        kept_dirs = []
        for name in dirs:
            candidate = Path(folder) / name
            if candidate.is_symlink() or os.path.isjunction(candidate):
                skipped.append(candidate)
            else:
                kept_dirs.append(name)
        dirs[:] = kept_dirs  # os.walk only descends into what stays in this list
        for name in files:
            candidate = Path(folder) / name
            (skipped if candidate.is_symlink() else found).append(candidate)
    return sorted(found), sorted(skipped)


def _safe_extract(zip_path: Path, destination: Path, max_bytes: int, report_problem) -> None:
    """Extract ``zip_path`` into ``destination`` with zip-slip and zip-bomb protection.

    A bad member (unsafe name, name clash, over-long path, encryption, I/O error) is reported
    through ``report_problem`` and skipped; it never aborts the whole import.
    """
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
        seen: set[str] = set()
        for member in members:
            if member.is_dir():
                continue
            try:
                target = (destination / member.filename).resolve()
                is_symlink = (member.external_attr >> 16) & 0o170000 == 0o120000
                if root not in target.parents or is_symlink:
                    report_problem(member.filename, "unsafe path or link inside zip; skipped")
                    continue
                key = str(target).lower()  # case-insensitive: Windows would overwrite otherwise
                if key in seen:
                    report_problem(member.filename, "same name appears twice in the zip; skipped")
                    continue
                seen.add(key)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as sink:
                    shutil.copyfileobj(source, sink, _CHUNK)
            except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as error:
                # OSError: name clash with a folder, path too long, disk full.
                # RuntimeError: encrypted member. NotImplementedError: unsupported compression.
                reason = f"could not extract: {type(error).__name__}: {error}"
                report_problem(member.filename, reason)


def _make_thumbnail(image: Image.Image, size: int) -> Image.Image:
    thumb = image.copy()
    thumb.thumbnail((size, size))
    if thumb.mode not in ("RGB", "L"):
        thumb = thumb.convert("RGB")
    return thumb


def _classify_and_store(
    path: Path, data: bytes, config: dict[str, Any], project_id: int, sha: str
) -> tuple[str, dict[str, Any] | str]:
    """Validate one image (already read into ``data``) and write its files.

    The file is read from disk once and the bytes are reused for hashing, decoding and the
    stored copy: on Windows each extra open of a new file is slow (file scanning).

    Returns ``("ok", info)`` or ``(outcome, reason)`` where outcome is ``"corrupt"`` or
    ``"oversize"``.
    """
    limits = config["images"]
    try:
        with Image.open(io.BytesIO(data)) as image:
            raw_width, raw_height = image.size  # from the header, nothing decoded yet
            if max(raw_width, raw_height) > limits["max_side_px"]:
                return "oversize", f"{raw_width}x{raw_height} exceeds {limits['max_side_px']} px"
            orientation = image.getexif().get(_EXIF_ORIENTATION, 1)
            width, height = raw_width, raw_height
            if orientation in _SWAPPING_ORIENTATIONS:
                width, height = raw_height, raw_width
            # JPEG only: decode at a reduced scale, which is much faster. The whole stream is still
            # read, so truncated files still fail in load(). A no-op for other formats.
            draft_side = limits["thumbnail_px"] * limits["thumbnail_draft_factor"]
            image.draft("RGB", (draft_side, draft_side))
            image.load()
            thumb = _make_thumbnail(ImageOps.exif_transpose(image), limits["thumbnail_px"])
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
    thumb.save(thumbs_folder / f"{sha}.jpg", format="JPEG", quality=limits["thumbnail_quality"])
    (images_folder / stored_name).write_bytes(data)
    return "ok", {
        "stored_name": stored_name,
        "width": width,
        "height": height,
        "bytes": len(data),
    }


def _run(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    project_id: int,
    files: list[Path],
    skipped_links: list[Path],
    display_root: Path,
    report: ImportReport,
    progress: ProgressCallback | None,
    cancelled: Callable[[], bool] | None,
) -> None:
    """Process ``files``, mutating ``report`` in place (so a crash keeps the counts so far)."""
    batch_id = report.batch_id
    allowed = {ext.lower() for ext in config["images"]["allowed_extensions"]}
    max_bytes = int(config["images"]["max_file_mb"] * _BYTES_PER_MB)
    max_problems = config["importing"]["max_problems_recorded"]
    every = max(1, int(config["importing"]["progress_every"]))

    def add_problem(name: str, reason: str) -> None:
        if len(report.problems) < max_problems:
            report.problems.append({"path": name, "reason": reason})
        else:
            report.problems_dropped += 1

    def import_one(path: Path, name: str) -> None:
        """Process one file and record exactly one outcome on the report."""
        if path.suffix.lower() not in allowed:
            report.unsupported += 1
            return
        try:
            if path.stat().st_size > max_bytes:
                report.oversize += 1
                add_problem(name, f"larger than {config['images']['max_file_mb']} MB")
                return
            data = path.read_bytes()
        except OSError as error:
            report.corrupt += 1
            add_problem(name, f"Cannot read file: {error}")
            return
        sha = hashlib.sha256(data).hexdigest()
        already = conn.execute(
            "SELECT 1 FROM images WHERE project_id = ? AND sha256 = ?", (project_id, sha)
        ).fetchone()
        if already:
            report.duplicates += 1
            return
        outcome, detail = _classify_and_store(path, data, config, project_id, sha)
        if outcome == "ok":
            conn.execute(
                "INSERT INTO images (project_id, batch_id, sha256, stored_name, original_name,"
                " width, height, bytes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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

    def display_name(path: Path) -> str:
        try:
            return str(path.relative_to(display_root))
        except ValueError:
            return path.name

    for link in skipped_links:  # reported, never silently dropped
        report.unsupported += 1
        add_problem(display_name(link), "symbolic link or junction; not followed")

    for index, path in enumerate(files, start=1):
        if cancelled is not None and cancelled():
            report.cancelled = True
            add_problem("(import)", f"cancelled after {index - 1} of {len(files)} files")
            break
        name = display_name(path)
        try:
            import_one(path, name)
        except sqlite3.Error:
            raise  # a database failure affects every file; stop instead of mislabelling them
        except Exception as error:  # one odd file must not abort the whole import
            report.corrupt += 1
            add_problem(name, f"{type(error).__name__}: {error}")
        if index % every == 0:
            conn.commit()
            if progress:
                progress(index, len(files), report)
    conn.commit()
    if progress:
        progress(len(files), len(files), report)


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
    cancelled: Callable[[], bool] | None = None,
) -> ImportReport:
    """Import a folder or a ``.zip`` into a project and return the report.

    ``cancelled`` is polled before each file; when it returns True the import stops cleanly,
    keeps what was already imported, and the report has ``cancelled = True``.

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
        extract_problems: list[tuple[str, str]] = []
        if is_zip:
            scratch = paths.data_dir(config) / "tmp"
            scratch.mkdir(parents=True, exist_ok=True)
            temp_root = Path(tempfile.mkdtemp(prefix="import_", dir=scratch))
            max_zip = int(config["importing"]["max_zip_uncompressed_gb"] * _BYTES_PER_GB)
            _safe_extract(
                source, temp_root, max_zip, lambda n, r: extract_problems.append((n, r))
            )
            files, skipped_links = list_candidate_files(temp_root)
            display_root = temp_root
        else:
            files, skipped_links = list_candidate_files(source)
            display_root = source
        max_problems = config["importing"]["max_problems_recorded"]
        for name, reason in extract_problems:  # zip members that could not be extracted
            report.corrupt += 1
            if len(report.problems) < max_problems:
                report.problems.append({"path": name, "reason": reason})
            else:
                report.problems_dropped += 1
        _run(
            conn,
            config,
            project_id,
            files,
            skipped_links,
            display_root,
            report,
            progress,
            cancelled,
        )
        return report
    finally:
        _write_batch(conn, report)
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)
