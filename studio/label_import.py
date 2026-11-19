"""Import labels (COCO json or a YOLO dataset) onto images already in a project.

Images are matched by file name (COCO: ``file_name``; YOLO: label file stem). An image's annotations
are REPLACED by the imported ones; images that are not in the project are listed, never created.
Classes are matched by name (ignoring case) and created when missing. Each annotation is checked
with the same rules as the editor; invalid ones are skipped and listed, the rest are kept.
"""

import json
import re
import shutil
import sqlite3
import uuid
from collections import defaultdict
from pathlib import Path, PurePath
from typing import Any

import yaml

from studio import annotations as validation
from studio import importer, paths
from studio import repo_annotations as ra
from studio.formats import coco, cvat, labelstudio, yolo


class LabelImportFailed(Exception):
    """The source cannot be read as COCO, CVAT, Label Studio or YOLO labels (says what to fix)."""


UPLOAD_PREFIX = re.compile(r"^[0-9a-f]{8}-")  # Label Studio prefixes uploaded files (believed)


def _clamp(kind: str, data: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    """Pull coordinates that overshoot the image edge back onto it (rounding in other tools)."""

    def cx(v: float) -> float:
        return min(max(v, 0.0), float(width))

    def cy(v: float) -> float:
        return min(max(v, 0.0), float(height))

    if kind == "box":
        x0, y0 = cx(data["x"]), cy(data["y"])
        x1, y1 = cx(data["x"] + data["w"]), cy(data["y"] + data["h"])
        return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
    if kind == "polygon":
        return {"points": [[cx(x), cy(y)] for x, y in data["points"]]}
    return {"points": [[cx(x), cy(y), v] if v else [0, 0, 0] for x, y, v in data["points"]]}


def _find_coco(root: Path) -> list[Path]:
    found = []
    for path in sorted(root.rglob("*.json")):
        try:
            head = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(head, dict)
            and isinstance(head.get("images"), list)
            and isinstance(head.get("annotations"), list)
        ):
            found.append(path)
    return found


def _find_cvat(root: Path) -> list[Path]:
    found = []
    for path in sorted(root.rglob("*.xml")):
        try:
            with path.open("rb") as handle:
                head = handle.read(2048)
        except OSError:
            continue
        if b"<annotations" in head:
            found.append(path)
    return found


def _find_labelstudio(root: Path) -> list[Path]:
    found = []
    for path in sorted(root.rglob("*.json")):
        try:
            head = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(head, list)
            and head
            and isinstance(head[0], dict)
            and isinstance(head[0].get("data"), dict)
        ):
            found.append(path)
    return found


def _order_points(cls: dict[str, Any], data: dict[str, Any], report: dict[str, Any], name: str):
    """Named points -> the class skeleton's order (points not in the set stay not labelled)."""
    skeleton = cls.get("skeleton")
    if not skeleton:
        report["skipped"].append(
            f"{name}: class '{cls['name']}' has no skeleton, keypoints skipped"
        )
        return None, None
    index = {n.casefold(): i for i, n in enumerate(skeleton["names"])}
    points = [[0.0, 0.0, 0] for _ in skeleton["names"]]
    for label, x, y in data["points"]:
        slot = index.get(str(label).casefold())
        if slot is None:
            report["skipped"].append(
                f"{name}: point '{label}' is not in the skeleton of '{cls['name']}'"
            )
            continue
        points[slot] = [x, y, 2]
    return "keypoints", {"points": points}


def _find_yolo(root: Path) -> tuple[Path | None, dict[str, Any]]:
    """The dataset yaml (names, kpt_shape) if there is one, and its parsed content."""
    for path in sorted(root.rglob("*.y*ml")):
        try:
            content = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(content, dict) and "names" in content:
            return path, content
    return None, {}


def _names_of(content: dict[str, Any]) -> list[str]:
    names = content.get("names")
    if isinstance(names, dict):
        try:
            return [str(names[k]) for k in sorted(names, key=lambda k: int(k))]
        except (TypeError, ValueError):
            return [str(names[k]) for k in sorted(names, key=str)]  # odd keys: still no crash
    if isinstance(names, list):
        return [str(n) for n in names]
    return []


def import_labels(
    conn: sqlite3.Connection, config: dict[str, Any], project_id: int, source: Path
) -> dict[str, Any]:
    """Apply the labels found in ``source`` (a folder or a .zip). Returns a report."""
    scratch = None
    root = source
    try:
        if source.is_file():
            scratch = paths.data_dir(config) / "tmp" / f"labels_{uuid.uuid4().hex[:10]}"
            scratch.mkdir(parents=True, exist_ok=True)
            problems: list[str] = []
            try:
                importer._safe_extract(
                    source,
                    scratch,
                    int(config["importing"]["max_zip_uncompressed_gb"] * 2**30),
                    lambda name, reason: problems.append(f"{name}: {reason}"),
                )
            except importer.ImportFailed as error:
                raise LabelImportFailed(str(error)) from error
            root = scratch
        elif not source.is_dir():
            raise LabelImportFailed("Choose a folder or a .zip file.")
        return _apply(conn, config, project_id, root)
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


def _apply(conn: sqlite3.Connection, config: dict[str, Any], project_id: int, root: Path):
    rows = conn.execute(
        "SELECT id, original_name, width, height FROM images WHERE project_id = ?", (project_id,)
    ).fetchall()
    by_name: dict[str, list[sqlite3.Row]] = defaultdict(list)
    by_stem: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        name = PurePath(row["original_name"]).name.lower()
        by_name[name].append(row)
        by_stem[PurePath(name).stem].append(row)

    coco_files = _find_coco(root)
    cvat_files = _find_cvat(root)
    ls_files = _find_labelstudio(root)
    yaml_path, yaml_content = _find_yolo(root)
    label_files = [
        p for p in sorted(root.rglob("*.txt")) if "labels" in {q.lower() for q in p.parts}
    ]
    others = bool(coco_files or cvat_files or ls_files)
    if not others and not label_files:
        raise LabelImportFailed(
            "Found no COCO .json file (with 'images' and 'annotations'), no CVAT .xml, no Label "
            "Studio .json (a list of tasks) and no YOLO 'labels' folder with .txt files in that "
            "source."
        )

    if coco_files:
        detected = "coco"
    elif cvat_files:
        detected = "cvat"
    elif ls_files:
        detected = "labelstudio"
    else:
        detected = "yolo"
    report: dict[str, Any] = {
        "format": detected,
        "matched_images": 0,
        "annotations_imported": 0,
        "unmatched_images": [],
        "skipped": [],
        "classes_created": [],
        "failed_images": [],
    }
    limits = config["annotations"]
    class_cache: dict[str, dict[str, Any]] = {
        c["name"].casefold(): c for c in ra.list_classes(conn, project_id)
    }

    def class_for(name: str, skeleton: dict[str, Any] | None) -> dict[str, Any]:
        found = class_cache.get(name.casefold())
        if found is None:
            clean = skeleton
            if skeleton:
                clean = validation.validate_skeleton(
                    skeleton, limits["max_keypoints"], limits["skeleton_name_max"]
                )
            found = ra.create_class(
                conn,
                project_id,
                ra.clean_class_name(name, config["projects"]["max_name_length"]),
                None,
                limits["palette"],
                clean,
            )
            class_cache[name.casefold()] = found
            report["classes_created"].append(found["name"])
        return found

    # image id -> (list of {class_id, kind, data}, mark_empty)
    pending: dict[int, tuple[list[dict[str, Any]], bool]] = {}
    origin: dict[int, str] = {}  # image id -> the label file that claimed it (first one wins)

    def claim(row: sqlite3.Row, source: str, label: str) -> bool:
        """An image takes labels from ONE file: a second file naming it is reported and ignored."""
        first = origin.setdefault(row["id"], source)
        if first != source:
            report["skipped"].append(
                f"{label}: also in {first}; kept the labels from {first}, ignored {source}"
            )
            return False
        return True

    def find_image(key: str, table: dict[str, list[sqlite3.Row]], label: str):
        matches = table.get(key.lower(), [])
        if not matches:
            report["unmatched_images"].append(label)
            return None
        if len(matches) > 1:
            report["skipped"].append(f"{label}: several images in the project have this name")
            return None
        return matches[0]

    def take(
        image: dict[str, Any], row: sqlite3.Row, pairs: list[tuple[Any, ...]], source: str
    ) -> None:
        """Queue one file entry's annotations for ``row`` (a size mismatch skips the image)."""
        if (
            image["width"]
            and image["height"]
            and (image["width"], image["height"]) != (row["width"], row["height"])
        ):
            report["skipped"].append(
                f"{image['file_name']}: size {image['width']}x{image['height']} in the "
                f"file but {row['width']}x{row['height']} here; skipped "
                "(coordinates would be wrong)"
            )
            return
        if not claim(row, source, image["file_name"]):
            return
        items = []
        for name, skeleton, kind, data in pairs:
            if kind == "named_keypoints":
                skeleton = {"names": [p[0] for p in data["points"]], "edges": []}
            cls = class_for(name, skeleton)
            if kind == "named_keypoints":
                kind, data = _order_points(cls, data, report, image["file_name"])
                if kind is None:
                    continue
            items.append({"class_id": cls["id"], "kind": kind, "data": data})
        if items:  # an image the file lists without annotations is left as it is
            pending.setdefault(row["id"], ([], False))[0].extend(items)

    for path in coco_files:
        try:
            parsed = coco.parse(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, KeyError, TypeError) as error:
            raise LabelImportFailed(f"{path.name}: {error}") from error
        report["skipped"] += [f"{path.name}: {note}" for note in parsed["skipped"]]
        for image in parsed["images"]:
            row = find_image(PurePath(image["file_name"]).name, by_name, image["file_name"])
            if row is None:
                continue
            pairs = []
            for ann in image["annotations"]:
                category = parsed["categories"].get(ann["category_id"])
                if category is None:
                    report["skipped"].append(
                        f"{image['file_name']}: unknown category {ann['category_id']}"
                    )
                    continue
                pairs.append((category["name"], category["skeleton"], ann["kind"], ann["data"]))
            take(image, row, pairs, path.name)

    def name_lookup(name: str) -> sqlite3.Row | None:
        """Match a CVAT / Label Studio file reference (path, URL, upload prefix) to an image."""
        base = PurePath(name.split("?")[0].replace("\\", "/")).name
        for candidate in (base, UPLOAD_PREFIX.sub("", base)):
            matches = by_name.get(candidate.lower(), [])
            if len(matches) == 1:
                return matches[0]
        return None

    def size_of(name: str):
        row = name_lookup(name)
        return (row["width"], row["height"]) if row else None

    def run_simple(path: Path, parsed: dict[str, Any]) -> None:
        report["skipped"] += [f"{path.name}: {note}" for note in parsed["skipped"]]
        for image in parsed["images"]:
            row = name_lookup(image["file_name"])
            if row is None:
                report["unmatched_images"].append(image["file_name"])
                continue
            pairs = [(a["label"], None, a["kind"], a["data"]) for a in image["annotations"]]
            take(image, row, pairs, path.name)

    for path in cvat_files:
        try:
            run_simple(path, cvat.parse(path.read_bytes()))
        except (cvat.CvatError, OSError) as error:
            raise LabelImportFailed(f"{path.name}: {error}") from error
    for path in ls_files:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            run_simple(path, labelstudio.parse(document, size_of))
        except (labelstudio.LabelStudioError, OSError, ValueError) as error:
            raise LabelImportFailed(f"{path.name}: {error}") from error

    if label_files and others:
        report["skipped"].append(
            f"{len(label_files)} YOLO label file(s) were ignored because this source also holds "
            f"{detected.upper()} labels; import them from a folder of their own"
        )
    if label_files and not others:
        names = _names_of(yaml_content)
        kpt = yaml_content.get("kpt_shape")
        for path in label_files:
            row = find_image(path.stem, by_stem, path.name)
            if row is None:
                continue
            if not claim(row, str(path.relative_to(root)), path.name):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                report["skipped"].append(f"{path.name}: could not be read as text")
                continue
            found, problems = yolo.parse_label_text(text, row["width"], row["height"], kpt)
            report["skipped"] += [f"{path.name}: {p}" for p in problems]
            items = []
            for ann in found:
                index = ann["class_index"]
                name = names[index] if index < len(names) else f"class {index}"
                skeleton = None
                if ann["kind"] == "keypoints":
                    skeleton = {
                        "names": [f"point {n + 1}" for n in range(len(ann["data"]["points"]))],
                        "edges": [],
                    }
                cls = class_for(name, skeleton)
                items.append({"class_id": cls["id"], "kind": ann["kind"], "data": ann["data"]})
            pending[row["id"]] = (items, not text.strip())  # a blank label file means "no objects"

    skeletons = {c["id"]: c["skeleton"] for c in class_cache.values()}
    sizes = {r["id"]: (r["width"], r["height"]) for r in rows}
    names_of_image = {r["id"]: r["original_name"] for r in rows}
    for image_id, (items, mark_empty) in pending.items():
        width, height = sizes[image_id]
        good = []
        for number, item in enumerate(items, start=1):
            try:
                data = _clamp(item["kind"], item["data"], width, height)
                checked = validation.validate_annotation(
                    {"kind": item["kind"], "data": data},
                    number,
                    width,
                    height,
                    limits,
                    skeletons.get(item["class_id"]),
                )
            except (validation.AnnotationError, KeyError, TypeError, ValueError) as error:
                report["skipped"].append(f"{names_of_image[image_id]}: {error}")
                continue
            good.append({"class_id": item["class_id"], **checked})
        if not good and not mark_empty:
            # Nothing usable came out of the file: keep the labels the image already has.
            report["skipped"].append(
                f"{names_of_image[image_id]}: no usable annotation in the file, so the existing "
                "labels were left as they are"
            )
            continue
        state = ra.get_annotations(conn, image_id)
        try:
            ra.save_annotations(
                conn,
                image_id,
                state["rev"],
                good,
                mark_empty and not good,
                state["label_class_id"],
                limits,
            )
        except validation.AnnotationError as error:
            report["failed_images"].append(f"{names_of_image[image_id]}: {error}")
            continue
        report["matched_images"] += 1
        report["annotations_imported"] += len(good)
    return report
