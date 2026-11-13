"""SQL for classes and annotations (same rules as ``repo.py``: functions of a connection, writes
commit before returning)."""

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from studio import annotations as validation
from studio.db import utc_now
from studio.repo import LABELLED_SQL

COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


class ClassExists(Exception):
    """A class with this name already exists in the project."""


class ClassInUse(Exception):
    """The class is used by annotations or image labels (``usage`` says how much)."""

    def __init__(self, message: str, usage: dict[str, int]) -> None:
        super().__init__(message)
        self.usage = usage


class RevisionConflict(Exception):
    """The image's annotations changed since the revision the client edited."""

    def __init__(self, current_rev: int) -> None:
        super().__init__(
            "These annotations were changed somewhere else since you opened the image."
        )
        self.current_rev = current_rev


# ---- classes ----------------------------------------------------------------------------------


def clean_class_name(name: str, max_length: int) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValueError("Class name cannot be empty.")
    if len(cleaned) > max_length:
        raise ValueError(f"Class name is longer than {max_length} characters.")
    return cleaned


def clean_color(color: str) -> str:
    if not COLOR_PATTERN.fullmatch(color):
        raise ValueError("Colour must look like #RRGGBB.")
    return color.upper()


def _class_dict(row: sqlite3.Row, usage: Mapping[str, int] | None = None) -> dict[str, Any]:
    skeleton = json.loads(row["skeleton"]) if row["skeleton"] else None
    result = {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "color": row["color"],
        "position": row["position"],
        "skeleton": skeleton,
    }
    if usage is not None:
        result.update(usage)
    return result


def _usage(conn: sqlite3.Connection, class_id: int) -> dict[str, int]:
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM annotations WHERE class_id = ?) AS annotations,"
        " (SELECT COUNT(DISTINCT image_id) FROM annotations WHERE class_id = ?) AS images,"
        " (SELECT COUNT(*) FROM images WHERE label_class_id = ?) AS labels",
        (class_id, class_id, class_id),
    ).fetchone()
    return {"annotations": row["annotations"], "images": row["images"], "labels": row["labels"]}


def get_class(conn: sqlite3.Connection, class_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
    return _class_dict(row, _usage(conn, class_id)) if row else None


def list_classes(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM classes WHERE project_id = ? ORDER BY position, id", (project_id,)
    ).fetchall()
    return [_class_dict(row, _usage(conn, row["id"])) for row in rows]


UNSET: Any = object()  # "argument not given" (None means "remove the skeleton")


def create_class(
    conn: sqlite3.Connection,
    project_id: int,
    name: str,
    color: str | None,
    palette: Sequence[str],
    skeleton: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a class. Without ``color`` the first unused palette colour is taken."""
    rows = conn.execute("SELECT color FROM classes WHERE project_id = ?", (project_id,)).fetchall()
    taken = {r["color"].upper() for r in rows}
    if color is None:
        # first unused palette colour; once all are used, cycle by how many classes exist
        color = next(
            (c for c in palette if c.upper() not in taken), palette[len(rows) % len(palette)]
        )
    position = conn.execute(
        "SELECT COALESCE(MAX(position) + 1, 0) FROM classes WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    try:
        cursor = conn.execute(
            "INSERT INTO classes (project_id, name, color, position, skeleton, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                project_id, name, color.upper(), position,
                validation.dumps(skeleton) if skeleton else None, utc_now(),
            ),
        )
    except sqlite3.IntegrityError as error:
        raise ClassExists(f"A class named '{name}' already exists.") from error
    conn.commit()
    return get_class(conn, int(cursor.lastrowid))  # type: ignore[return-value]


def update_class(
    conn: sqlite3.Connection,
    class_id: int,
    name: str | None,
    color: str | None,
    position: int | None,
    skeleton: Any = UNSET,
) -> dict[str, Any] | None:
    """Change a class's name, colour, position or skeleton. None if it does not exist.

    ``skeleton`` is already cleaned; ``None`` removes it, ``UNSET`` leaves it alone. Once the class
    has keypoint annotations the number of points cannot change (the stored points would no
    longer line up with the names).
    """
    # Take the write lock FIRST, like save_annotations: the point-count check below and the
    # UPDATE must not have a keypoint save slip in between them.
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
        if current is None:
            conn.rollback()
            return None
        skeleton_json = current["skeleton"]
        if skeleton is not UNSET:
            old = json.loads(current["skeleton"]) if current["skeleton"] else None
            used = conn.execute(
                "SELECT COUNT(*) FROM annotations WHERE class_id = ? AND kind = 'keypoints'",
                (class_id,),
            ).fetchone()[0]
            old_count = len(old["names"]) if old else None
            new_count = len(skeleton["names"]) if skeleton else None
            if used and old_count != new_count:
                raise ValueError(
                    f"{used} keypoint annotation(s) use this skeleton, so its number of points "
                    "cannot change. Rename points or change edges, or delete those annotations "
                    "first."
                )
            skeleton_json = validation.dumps(skeleton) if skeleton else None
        try:
            conn.execute(
                "UPDATE classes SET name = ?, color = ?, position = ?, skeleton = ? WHERE id = ?",
                (
                    name if name is not None else current["name"],
                    color.upper() if color is not None else current["color"],
                    position if position is not None else current["position"],
                    skeleton_json,
                    class_id,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ClassExists(f"A class named '{name}' already exists.") from error
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return get_class(conn, class_id)


def delete_class(conn: sqlite3.Connection, class_id: int, force: bool) -> bool:
    """Delete a class. Refuses (``ClassInUse``) if it is used, unless ``force``.

    With ``force`` its annotations are deleted and image labels of this class are cleared.
    Returns False if the class does not exist.
    """
    if conn.execute("SELECT 1 FROM classes WHERE id = ?", (class_id,)).fetchone() is None:
        return False
    usage = _usage(conn, class_id)
    if not force and (usage["annotations"] or usage["labels"]):
        raise ClassInUse(
            f"This class is used by {usage['annotations']} annotation(s) and "
            f"{usage['labels']} image label(s).",
            usage,
        )
    # Bump the revision of images that are about to lose annotations, so open editors notice.
    conn.execute(
        "UPDATE images SET annotations_rev = annotations_rev + 1 WHERE id IN"
        " (SELECT image_id FROM annotations WHERE class_id = ?) OR label_class_id = ?",
        (class_id, class_id),
    )
    conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))
    conn.commit()
    return True


# ---- annotations ------------------------------------------------------------------------------


def get_annotations(conn: sqlite3.Connection, image_id: int) -> dict[str, Any] | None:
    image = conn.execute(
        "SELECT id, marked_empty, label_class_id, annotations_rev FROM images WHERE id = ?",
        (image_id,),
    ).fetchone()
    if image is None:
        return None
    rows = conn.execute(
        "SELECT class_id, kind, data FROM annotations WHERE image_id = ? ORDER BY position, id",
        (image_id,),
    ).fetchall()
    return {
        "rev": image["annotations_rev"],
        "marked_empty": bool(image["marked_empty"]),
        "label_class_id": image["label_class_id"],
        "annotations": [
            {"class_id": r["class_id"], "kind": r["kind"], "data": json.loads(r["data"])}
            for r in rows
        ],
    }


def save_annotations(
    conn: sqlite3.Connection,
    image_id: int,
    rev: int,
    items: Sequence[Mapping[str, Any]],
    marked_empty: bool,
    label_class_id: int | None,
    limits: Mapping[str, Any],
) -> int:
    """Replace an image's annotations atomically and return the new revision.

    Raises:
        RevisionConflict: ``rev`` is not the current revision.
        validation.AnnotationError: invalid content (nothing is written).
        LookupError: the image does not exist.
    """
    now = utc_now()
    try:
        # Take the write lock FIRST. Reading the revision, the project's classes and validating
        # all happen inside it, so nothing (a class deleted, another save) can slip in between the
        # checks and the write.
        conn.execute("BEGIN IMMEDIATE")
        image = conn.execute(
            "SELECT id, project_id, width, height, annotations_rev FROM images WHERE id = ?",
            (image_id,),
        ).fetchone()
        if image is None:
            raise LookupError(f"Image {image_id} not found.")
        if rev != image["annotations_rev"]:
            raise RevisionConflict(image["annotations_rev"])

        validation.validate_set(items, marked_empty, limits)
        classes = {
            r["id"]: (json.loads(r["skeleton"]) if r["skeleton"] else None)
            for r in conn.execute(
                "SELECT id, skeleton FROM classes WHERE project_id = ?", (image["project_id"],)
            )
        }
        if label_class_id is not None and label_class_id not in classes:
            raise validation.AnnotationError("The image label is not a class of this project.")
        cleaned = []
        for index, item in enumerate(items, start=1):
            class_id = item.get("class_id")
            if class_id not in classes:
                raise validation.AnnotationError(
                    f"Annotation {index}: its class is not part of this project."
                )
            result = validation.validate_annotation(
                item, index, image["width"], image["height"], limits, classes[class_id]
            )
            cleaned.append((class_id, result["kind"], validation.dumps(result["data"])))

        conn.execute("DELETE FROM annotations WHERE image_id = ?", (image_id,))
        conn.executemany(
            "INSERT INTO annotations (image_id, class_id, kind, data, position, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(image_id, c, k, d, i, now, now) for i, (c, k, d) in enumerate(cleaned)],
        )
        conn.execute(
            "UPDATE images SET marked_empty = ?, label_class_id = ?,"
            " annotations_rev = annotations_rev + 1 WHERE id = ?",
            (1 if marked_empty else 0, label_class_id, image_id),
        )
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    return rev + 1


# ---- progress and navigation ------------------------------------------------------------------


def annotation_stats(conn: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    """Progress numbers and per-class counts for one project."""
    totals = conn.execute(
        f"SELECT COUNT(*) AS images,"
        f" SUM(CASE WHEN {LABELLED_SQL} THEN 1 ELSE 0 END) AS labelled,"
        f" SUM(i.marked_empty) AS empty,"
        f" SUM(CASE WHEN EXISTS (SELECT 1 FROM annotations a WHERE a.image_id = i.id)"
        f" THEN 1 ELSE 0 END) AS with_annotations,"
        f" SUM(CASE WHEN i.label_class_id IS NOT NULL THEN 1 ELSE 0 END) AS with_label"
        f" FROM images i WHERE i.project_id = ?",
        (project_id,),
    ).fetchone()
    per_class = []
    for cls in list_classes(conn, project_id):
        kinds = {
            r["kind"]: r["n"]
            for r in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM annotations WHERE class_id = ? GROUP BY kind",
                (cls["id"],),
            )
        }
        per_class.append(
            {
                "class_id": cls["id"],
                "name": cls["name"],
                "color": cls["color"],
                "boxes": kinds.get("box", 0),
                "polygons": kinds.get("polygon", 0),
                "keypoints": kinds.get("keypoints", 0),
                "images": cls["images"],
                "labels": cls["labels"],
            }
        )
    labelled = totals["labelled"] or 0
    return {
        "images": totals["images"],
        "labelled": labelled,
        "unlabelled": totals["images"] - labelled,
        "marked_empty": totals["empty"] or 0,
        "with_annotations": totals["with_annotations"] or 0,
        "with_label": totals["with_label"] or 0,
        "per_class": per_class,
    }


def neighbours(conn: sqlite3.Connection, image_id: int) -> dict[str, Any] | None:
    """Previous/next image ids (by id, within the project), position, and next unlabelled image."""
    image = conn.execute("SELECT id, project_id FROM images WHERE id = ?", (image_id,)).fetchone()
    if image is None:
        return None
    project_id = image["project_id"]

    def one(sql: str, *args: Any) -> Any:
        return conn.execute(sql, args).fetchone()[0]

    unlabelled = f"i.project_id = ? AND NOT {LABELLED_SQL}"
    next_unlabelled = one(
        f"SELECT MIN(i.id) FROM images i WHERE {unlabelled} AND i.id > ?", project_id, image_id
    )
    if next_unlabelled is None:  # wrap around, but never answer with the current image itself
        next_unlabelled = one(
            f"SELECT MIN(i.id) FROM images i WHERE {unlabelled} AND i.id != ?", project_id, image_id
        )
    return {
        "previous": one(
            "SELECT MAX(id) FROM images WHERE project_id = ? AND id < ?", project_id, image_id
        ),
        "next": one(
            "SELECT MIN(id) FROM images WHERE project_id = ? AND id > ?", project_id, image_id
        ),
        "next_unlabelled": next_unlabelled,
        "index": one(
            "SELECT COUNT(*) FROM images WHERE project_id = ? AND id <= ?", project_id, image_id
        ),
        "total": one("SELECT COUNT(*) FROM images WHERE project_id = ?", project_id),
    }
