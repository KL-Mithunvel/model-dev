"""Data-access functions (SQL lives here, nowhere else). Pure functions of a connection.

Every function takes an open ``sqlite3.Connection``; the caller owns its lifetime. Functions that
write commit before returning.
"""

import json
import shutil
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from studio import paths, splits
from studio.db import utc_now

UNASSIGNED = "unassigned"
SPLIT_FILTERS = (*splits.SPLIT_NAMES, UNASSIGNED)


class ProjectExists(Exception):
    """A project with this name already exists."""


def clean_name(name: str, max_length: int) -> str:
    """Trim and validate a project name.

    Raises:
        ValueError: empty after trimming, or longer than ``max_length``.
    """
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValueError("Project name cannot be empty.")
    if len(cleaned) > max_length:
        raise ValueError(f"Project name is longer than {max_length} characters.")
    return cleaned


def clean_tags(tags: Sequence[str], max_length: int, max_count: int) -> list[str]:
    """Normalise tags: trimmed, lower-case, de-duplicated, order kept.

    Raises:
        ValueError: a tag is empty/too long, or there are more than ``max_count`` tags.
    """
    result: list[str] = []
    for raw in tags:
        tag = " ".join(raw.split()).lower()
        if not tag:
            raise ValueError("Tags cannot be empty.")
        if len(tag) > max_length:
            raise ValueError(f"Tag '{tag[:20]}…' is longer than {max_length} characters.")
        if tag not in result:
            result.append(tag)
    if len(result) > max_count:
        raise ValueError(f"An image can have at most {max_count} tags.")
    return result


# ---- projects -------------------------------------------------------------------------------


def _project_row(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    counts = {name: 0 for name in splits.SPLIT_NAMES}
    counts[UNASSIGNED] = 0
    for entry in conn.execute(
        "SELECT COALESCE(split, 'unassigned') AS s, COUNT(*) AS n FROM images"
        " WHERE project_id = ? GROUP BY s",
        (row["id"],),
    ):
        counts[entry["s"]] = entry["n"]
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "image_count": sum(counts.values()),
        "split_counts": counts,
    }


def create_project(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    """Create a project. Raises ``ProjectExists`` if the name is taken."""
    try:
        cursor = conn.execute(
            "INSERT INTO projects (name, created_at) VALUES (?, ?)", (name, utc_now())
        )
    except sqlite3.IntegrityError as error:
        raise ProjectExists(f"A project named '{name}' already exists.") from error
    conn.commit()
    return get_project(conn, int(cursor.lastrowid))  # type: ignore[return-value]


def get_project(conn: sqlite3.Connection, project_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project_row(conn, row) if row else None


def list_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM projects ORDER BY name COLLATE NOCASE").fetchall()
    return [_project_row(conn, row) for row in rows]


def delete_project(conn: sqlite3.Connection, config: dict[str, Any], project_id: int) -> bool:
    """Delete a project, its rows and its files. Returns False if it did not exist."""
    cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    shutil.rmtree(paths.project_dir(config, project_id), ignore_errors=True)
    return cursor.rowcount > 0


# ---- images ---------------------------------------------------------------------------------


def _image_dict(row: sqlite3.Row, tags: list[str]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "batch_id": row["batch_id"],
        "original_name": row["original_name"],
        "width": row["width"],
        "height": row["height"],
        "bytes": row["bytes"],
        "split": row["split"],
        "sha256": row["sha256"],
        "tags": tags,
        "created_at": row["created_at"],
    }


def _tags_for(conn: sqlite3.Connection, image_ids: Sequence[int]) -> dict[int, list[str]]:
    found: dict[int, list[str]] = {image_id: [] for image_id in image_ids}
    if not image_ids:
        return found
    marks = ",".join("?" * len(image_ids))
    for row in conn.execute(
        f"SELECT image_id, tag FROM image_tags WHERE image_id IN ({marks}) ORDER BY tag",
        list(image_ids),
    ):
        found[row["image_id"]].append(row["tag"])
    return found


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_images(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    offset: int = 0,
    limit: int = 60,
    split: str | None = None,
    tag: str | None = None,
    batch_id: int | None = None,
    query: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of images and the total number matching the filters.

    Raises:
        ValueError: ``split`` is not one of train/val/test/unassigned.
    """
    where = ["i.project_id = ?"]
    args: list[Any] = [project_id]
    if split is not None:
        if split not in SPLIT_FILTERS:
            raise ValueError(f"split must be one of {list(SPLIT_FILTERS)}")
        where.append("i.split IS NULL" if split == UNASSIGNED else "i.split = ?")
        if split != UNASSIGNED:
            args.append(split)
    if tag:
        where.append("EXISTS (SELECT 1 FROM image_tags t WHERE t.image_id = i.id AND t.tag = ?)")
        args.append(tag.strip().lower())
    if batch_id is not None:
        where.append("i.batch_id = ?")
        args.append(batch_id)
    if query:
        where.append("i.original_name LIKE ? ESCAPE '\\'")
        args.append(f"%{_escape_like(query.strip())}%")
    clause = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM images i WHERE {clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT i.* FROM images i WHERE {clause} ORDER BY i.id LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    tags = _tags_for(conn, [row["id"] for row in rows])
    return [_image_dict(row, tags[row["id"]]) for row in rows], total


def get_image(conn: sqlite3.Connection, image_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
    if row is None:
        return None
    image = _image_dict(row, _tags_for(conn, [image_id])[image_id])
    image["stored_name"] = row["stored_name"]
    return image


def set_tags(conn: sqlite3.Connection, image_id: int, tags: list[str]) -> None:
    """Replace an image's tags (already cleaned with ``clean_tags``)."""
    conn.execute("DELETE FROM image_tags WHERE image_id = ?", (image_id,))
    conn.executemany(
        "INSERT INTO image_tags (image_id, tag) VALUES (?, ?)", [(image_id, tag) for tag in tags]
    )
    conn.commit()


def project_tags(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    """Return every tag used in a project with its image count."""
    rows = conn.execute(
        "SELECT t.tag AS tag, COUNT(*) AS n FROM image_tags t JOIN images i ON i.id = t.image_id"
        " WHERE i.project_id = ? GROUP BY t.tag ORDER BY t.tag",
        (project_id,),
    )
    return [{"tag": row["tag"], "count": row["n"]} for row in rows]


def set_split(
    conn: sqlite3.Connection, project_id: int, image_ids: Sequence[int], split: str | None
) -> int:
    """Set (or clear, with ``None``) the split of the given images. Returns rows changed.

    Raises:
        ValueError: ``split`` is not train/val/test/None.
    """
    if split is not None and split not in splits.SPLIT_NAMES:
        raise ValueError(f"split must be one of {list(splits.SPLIT_NAMES)} or null")
    if not image_ids:
        return 0
    marks = ",".join("?" * len(image_ids))
    cursor = conn.execute(
        f"UPDATE images SET split = ? WHERE project_id = ? AND id IN ({marks})",
        [split, project_id, *image_ids],
    )
    conn.commit()
    return cursor.rowcount


def apply_splits(
    conn: sqlite3.Connection,
    project_id: int,
    ratios: Mapping[str, float],
    seed: int,
    only_unassigned: bool,
) -> tuple[dict[str, int], dict[str, list[int]]]:
    """Randomly assign splits to a project's images.

    Returns ``(assigned_counts, previous)`` where ``previous`` maps each former split
    (``train``/``val``/``test``/``unassigned``) to the image ids that had it, so a caller can undo.

    Raises:
        ValueError: invalid ratios.
    """
    splits.validate_ratios(ratios)
    condition = " AND split IS NULL" if only_unassigned else ""
    before = conn.execute(
        f"SELECT id, split FROM images WHERE project_id = ?{condition} ORDER BY id", (project_id,)
    ).fetchall()
    previous: dict[str, list[int]] = {name: [] for name in SPLIT_FILTERS}
    for row in before:
        previous[row["split"] or UNASSIGNED].append(row["id"])
    assignment = splits.assign_splits([row["id"] for row in before], ratios, seed)
    conn.executemany(
        "UPDATE images SET split = ? WHERE id = ?",
        [(name, image_id) for image_id, name in assignment.items()],
    )
    conn.commit()
    counts = {name: list(assignment.values()).count(name) for name in splits.SPLIT_NAMES}
    return counts, previous


# ---- batches --------------------------------------------------------------------------------


def list_batches(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM batches WHERE project_id = ? ORDER BY id DESC", (project_id,)
    ).fetchall()
    return [
        {
            "id": row["id"],
            "source": row["source"],
            "created_at": row["created_at"],
            "added": row["added"],
            "duplicates": row["duplicates"],
            "corrupt": row["corrupt"],
            "oversize": row["oversize"],
            "unsupported": row["unsupported"],
            "problems": json.loads(row["problems"]),
        }
        for row in rows
    ]
