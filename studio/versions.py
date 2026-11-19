"""Immutable dataset versions (Stage 3.3).

A version freezes the LABELLED images of a project (annotations, "no objects" marks or a class
label): each image's split, size and labels, the class table and a recorded preprocessing
description. Classes are kept by name. The ``content_hash`` is the SHA-256 of a canonical JSON form
of that content (sorted keys, images ordered by sha256, annotations in a fixed order), so it does
NOT depend on database ids, version names or timestamps: the same project state always gives the
same hash, and creating a version identical to an existing one is refused.

Image bytes are not copied (they are stored by sha256 and never change). Nothing here edits a
version after creation; the only mutation is ``delete_version``.
"""

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from studio import repo_annotations as ra
from studio.db import utc_now

SCHEMA = 1


class VersionError(Exception):
    """The version cannot be created or read (the message says why and what to do)."""


class VersionExists(VersionError):
    """A version with exactly this content already exists."""

    def __init__(self, number: int) -> None:
        super().__init__(
            f"The project is unchanged since version {number}: a new version would be identical. "
            "Change labels, splits or classes first."
        )
        self.number = number


def clean_name(name: str | None, max_length: int) -> str:
    text = " ".join((name or "").split())
    if len(text) > max_length:
        raise VersionError(f"A version name can have at most {max_length} characters.")
    return text


def check_preprocessing(value: Any, max_bytes: int) -> dict[str, Any]:
    """The preprocessing description: a JSON object, recorded as given (not applied yet)."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise VersionError('Preprocessing must be an object such as {"resize": 640}.')
    try:
        text = json.dumps(value, sort_keys=True, allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise VersionError(f"Preprocessing must be plain JSON: {error}") from error
    if len(text.encode("utf-8")) > max_bytes:
        raise VersionError(f"Preprocessing is longer than {max_bytes} bytes.")
    return json.loads(text)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_payload(
    classes: Sequence[Mapping[str, Any]],
    images: Sequence[Mapping[str, Any]],
    preprocessing: Mapping[str, Any],
) -> dict[str, Any]:
    """The hashed content. ``classes`` are in class order; ``images`` carry class NAMES."""
    out_images = []
    for image in images:
        annotations = sorted(
            (
                {"class": a["class"], "kind": a["kind"], "data": a["data"]}
                for a in image["annotations"]
            ),
            key=_canonical,
        )
        out_images.append(
            {
                "sha256": image["sha256"],
                "original_name": image["original_name"],
                "width": image["width"],
                "height": image["height"],
                "split": image["split"],
                "marked_empty": bool(image["marked_empty"]),
                "label_class": image["label_class"],
                "annotations": annotations,
            }
        )
    out_images.sort(key=lambda i: i["sha256"])
    return {
        "schema": SCHEMA,
        "classes": [{"name": c["name"], "skeleton": c.get("skeleton") or None} for c in classes],
        "images": out_images,
        "preprocessing": dict(preprocessing),
    }


def content_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _live_images(conn: sqlite3.Connection, project_id: int) -> tuple[list[dict[str, Any]], int]:
    """Labelled images of the project with class NAMES, and how many unlabelled were left out."""
    names = {
        r["id"]: r["name"]
        for r in conn.execute("SELECT id, name FROM classes WHERE project_id = ?", (project_id,))
    }
    rows = conn.execute(
        "SELECT id, sha256, original_name, stored_name, width, height, split, marked_empty,"
        " label_class_id FROM images WHERE project_id = ? ORDER BY id",
        (project_id,),
    ).fetchall()
    by_image: dict[int, list[dict[str, Any]]] = {}
    for row in conn.execute(
        "SELECT a.image_id, a.class_id, a.kind, a.data FROM annotations a"
        " JOIN images i ON i.id = a.image_id WHERE i.project_id = ?"
        " ORDER BY a.image_id, a.position",
        (project_id,),
    ):
        by_image.setdefault(row["image_id"], []).append(
            {"class": names[row["class_id"]], "kind": row["kind"], "data": json.loads(row["data"])}
        )
    images, unlabelled = [], 0
    for row in rows:
        annotations = by_image.get(row["id"], [])
        label_class = names.get(row["label_class_id"]) if row["label_class_id"] else None
        if not (annotations or row["marked_empty"] or label_class):
            unlabelled += 1
            continue
        images.append({**dict(row), "annotations": annotations, "label_class": label_class})
    return images, unlabelled


def create_version(
    conn: sqlite3.Connection,
    project_id: int,
    name: str | None,
    preprocessing: Any,
    limits: Mapping[str, Any],
) -> dict[str, Any]:
    """Snapshot the project now. Raises ``VersionError`` / ``VersionExists`` (nothing written)."""
    name = clean_name(name, limits["max_name_length"])
    preprocessing = check_preprocessing(preprocessing, limits["max_preprocessing_bytes"])
    # Write lock first: the copy must see one consistent state, with no save slipping in.
    conn.execute("BEGIN IMMEDIATE")
    try:
        project = conn.execute(
            "SELECT id, next_version FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if project is None:
            raise LookupError(f"Project {project_id} not found.")
        classes = ra.list_classes(conn, project_id)
        images, unlabelled = _live_images(conn, project_id)
        if not images:
            raise VersionError(
                "There are no labelled images to freeze yet. Label some images first."
            )
        existing_count = conn.execute(
            "SELECT COUNT(*) FROM dataset_versions WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        if existing_count >= limits["max_per_project"]:
            raise VersionError(
                f"A project can hold at most {limits['max_per_project']} versions. Delete old ones."
            )
        payload = build_payload(classes, images, preprocessing)
        digest = content_hash(payload)
        same = conn.execute(
            "SELECT number FROM dataset_versions WHERE project_id = ? AND content_hash = ?",
            (project_id, digest),
        ).fetchone()
        if same is not None:
            raise VersionExists(same["number"])
        splits: dict[str, int] = {}
        for image in images:
            key = image["split"] or "unassigned"
            splits[key] = splits.get(key, 0) + 1
        annotation_count = sum(len(i["annotations"]) for i in images)
        manifest = {
            "schema": SCHEMA,
            "content_hash": digest,
            "classes": [
                {"name": c["name"], "color": c["color"], "skeleton": c.get("skeleton") or None}
                for c in classes
            ],
            "preprocessing": preprocessing,
            "splits": splits,
            "excluded_unlabelled": unlabelled,
        }
        number = project["next_version"]
        cursor = conn.execute(
            "INSERT INTO dataset_versions (project_id, number, name, created_at, content_hash,"
            " manifest, image_count, annotation_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                number,
                name,
                utc_now(),
                digest,
                json.dumps(manifest, sort_keys=True, ensure_ascii=False),
                len(images),
                annotation_count,
            ),
        )
        version_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO version_images (version_id, sha256, original_name, stored_name, width,"
            " height, split, marked_empty, label_class, annotations)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    version_id,
                    i["sha256"],
                    i["original_name"],
                    i["stored_name"],
                    i["width"],
                    i["height"],
                    i["split"],
                    int(bool(i["marked_empty"])),
                    i["label_class"],
                    json.dumps(i["annotations"], sort_keys=True, ensure_ascii=False),
                )
                for i in images
            ],
        )
        conn.execute("UPDATE projects SET next_version = ? WHERE id = ?", (number + 1, project_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return get_version(conn, version_id)  # type: ignore[return-value]


def _summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "number": row["number"],
        "name": row["name"],
        "created_at": row["created_at"],
        "content_hash": row["content_hash"],
        "image_count": row["image_count"],
        "annotation_count": row["annotation_count"],
    }


def list_versions(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, project_id, number, name, created_at, content_hash, image_count,"
        " annotation_count FROM dataset_versions WHERE project_id = ? ORDER BY number DESC",
        (project_id,),
    )
    return [_summary(r) for r in rows]


def _stored_images(conn: sqlite3.Connection, version_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM version_images WHERE version_id = ? ORDER BY sha256", (version_id,)
    )
    return [
        {
            **dict(r),
            "annotations": json.loads(r["annotations"]),
            "marked_empty": bool(r["marked_empty"]),
        }
        for r in rows
    ]


def get_version(conn: sqlite3.Connection, version_id: int) -> dict[str, Any] | None:
    """The version with its manifest and ``intact``: stored rows still hash to ``content_hash``."""
    row = conn.execute("SELECT * FROM dataset_versions WHERE id = ?", (version_id,)).fetchone()
    if row is None:
        return None
    manifest = json.loads(row["manifest"])
    payload = build_payload(
        manifest["classes"], _stored_images(conn, version_id), manifest["preprocessing"]
    )
    return {
        **_summary(row),
        "manifest": manifest,
        "intact": content_hash(payload) == row["content_hash"],
    }


def delete_version(conn: sqlite3.Connection, version_id: int) -> bool:
    cursor = conn.execute("DELETE FROM dataset_versions WHERE id = ?", (version_id,))
    conn.commit()
    return cursor.rowcount > 0


def export_data(
    conn: sqlite3.Connection, version_id: int
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]] | None:
    """``(project_id, classes, images)`` in the shape ``exporter.export_data`` takes.

    Class ids are the position in the version's class table (1-based); image ids are 1-based in
    sha256 order. Live ids are not used: they may no longer exist.
    """
    row = conn.execute(
        "SELECT project_id, manifest FROM dataset_versions WHERE id = ?", (version_id,)
    ).fetchone()
    if row is None:
        return None
    manifest = json.loads(row["manifest"])
    classes = [
        {"id": n, "name": c["name"], "color": c["color"], "skeleton": c["skeleton"], "position": n}
        for n, c in enumerate(manifest["classes"], start=1)
    ]
    ids = {c["name"]: c["id"] for c in classes}
    images = []
    for number, image in enumerate(_stored_images(conn, version_id), start=1):
        images.append(
            {
                "id": number,
                "original_name": image["original_name"],
                "stored_name": image["stored_name"],
                "sha256": image["sha256"],
                "width": image["width"],
                "height": image["height"],
                "split": image["split"],
                "marked_empty": image["marked_empty"],
                "annotations": [
                    {"class_id": ids[a["class"]], "kind": a["kind"], "data": a["data"]}
                    for a in image["annotations"]
                ],
            }
        )
    return row["project_id"], classes, images
