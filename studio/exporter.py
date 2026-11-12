"""Export a project's labels (and optionally its images) as a COCO or YOLO zip.

Which images are included: labelled ones only (they have annotations, or were marked "no objects").
If any included image has a split, images without a split are left out and reported; if none has,
they all go to ``train``. Nothing is written for ``dry_run``; the report is the same.
"""

import json
import sqlite3
import zipfile
from collections import defaultdict
from pathlib import Path, PurePath
from typing import Any

from studio import paths
from studio import repo_annotations as ra
from studio.formats import coco, yolo

FORMATS = ("coco", "yolo")


class ExportError(Exception):
    """The project cannot be exported the way it was asked (the message says why and what to do)."""


def _load(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    images = [
        dict(row)
        for row in conn.execute(
            "SELECT id, original_name, stored_name, sha256, width, height, split, marked_empty"
            " FROM images WHERE project_id = ? ORDER BY id",
            (project_id,),
        )
    ]
    by_image: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in conn.execute(
        "SELECT a.image_id, a.class_id, a.kind, a.data FROM annotations a"
        " JOIN images i ON i.id = a.image_id WHERE i.project_id = ?"
        " ORDER BY a.image_id, a.position",
        (project_id,),
    ):
        by_image[row["image_id"]].append(
            {"class_id": row["class_id"], "kind": row["kind"], "data": json.loads(row["data"])}
        )
    for image in images:
        image["annotations"] = by_image.get(image["id"], [])
    return images


def _unique_names(images: list[dict[str, Any]]) -> None:
    """Give every exported image a file name that is unique in the zip."""
    taken: dict[str, int] = defaultdict(int)
    for image in images:
        taken[PurePath(image["original_name"]).stem.lower()] += 1  # YOLO pairs files by stem
    for image in images:
        name = PurePath(image["original_name"]).name
        if taken[PurePath(name).stem.lower()] > 1:
            path = PurePath(name)
            name = f"{path.stem}_{image['sha256'][:8]}{path.suffix}"
        image["file_name"] = name


def export_project(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    project_id: int,
    fmt: str,
    task: str = "detect",
    include_images: bool = True,
    dest: Path | None = None,
) -> dict[str, Any]:
    """Write the zip to ``dest`` (or only compute the report when ``dest`` is None)."""
    if fmt not in FORMATS:
        raise ExportError(f"Unknown format '{fmt}'. Use one of {list(FORMATS)}.")
    if fmt == "yolo" and task not in yolo.TASKS:
        raise ExportError(f"Unknown YOLO task '{task}'. Use one of {list(yolo.TASKS)}.")
    classes = ra.list_classes(conn, project_id)
    if not classes:
        raise ExportError("This project has no classes yet, so there is nothing to export.")
    everything = _load(conn, project_id)
    labelled = [i for i in everything if i["annotations"] or i["marked_empty"]]
    any_split = any(i["split"] for i in labelled)
    included = [i for i in labelled if i["split"] or not any_split]
    for image in included:
        image["export_split"] = image["split"] or "train"
    _unique_names(included)

    class_index = {c["id"]: n for n, c in enumerate(classes)}
    kpt_shape = None
    if fmt == "yolo" and task == "pose":
        sizes = {len(c["skeleton"]["names"]) for c in classes if c["skeleton"]}
        if len(sizes) != 1:
            raise ExportError(
                "YOLO pose needs every keypoint class to have the same number of points "
                f"(this project has {sorted(sizes) or 'no keypoint classes'}). Use COCO instead."
            )
        kpt_shape = (sizes.pop(), 3)

    report: dict[str, Any] = {
        "format": fmt,
        "task": task if fmt == "yolo" else None,
        "images": len(included),
        "annotations": sum(len(i["annotations"]) for i in included),
        "skipped_annotations": 0,
        "excluded_unlabelled": len(everything) - len(labelled),
        "excluded_unassigned": len(labelled) - len(included),
        "splits": {},
        "includes_images": include_images,
    }
    for image in included:
        report["splits"][image["export_split"]] = report["splits"].get(image["export_split"], 0) + 1
    if fmt == "yolo":
        for image in included:
            _, skipped = yolo.export_lines(
                task, image["annotations"], class_index, image["width"], image["height"]
            )
            report["skipped_annotations"] += skipped
        report["annotations"] -= report["skipped_annotations"]
    if dest is None:
        return report
    if not included:
        raise ExportError("No labelled images to export yet. Label some images first.")

    images_folder = paths.images_dir(config, project_id)
    with zipfile.ZipFile(dest, "w") as archive:

        def add_text(name: str, text: str) -> None:
            archive.writestr(name, text, compress_type=zipfile.ZIP_DEFLATED)

        def add_image(image: dict[str, Any], folder: str) -> None:
            source = images_folder / image["stored_name"]
            if include_images and source.is_file():
                archive.write(source, f"{folder}/{image['file_name']}", zipfile.ZIP_STORED)

        splits = sorted({i["export_split"] for i in included})
        if fmt == "coco":
            for split in splits:
                members = [i for i in included if i["export_split"] == split]
                document = coco.build(members, classes, f"{split} split")
                add_text(f"annotations/instances_{split}.json", json.dumps(document, indent=1))
                for image in members:
                    add_image(image, f"images/{split}")
        else:
            for image in included:
                lines, _ = yolo.export_lines(
                    task, image["annotations"], class_index, image["width"], image["height"]
                )
                stem = PurePath(image["file_name"]).stem
                add_text(
                    f"labels/{image['export_split']}/{stem}.txt",
                    "\n".join(lines) + "\n" * bool(lines),
                )
                add_image(image, f"images/{image['export_split']}")
            add_text(
                "data.yaml", yolo.dataset_yaml([c["name"] for c in classes], splits, kpt_shape)
            )
        add_text("export_report.json", json.dumps(report, indent=1))
    return report
