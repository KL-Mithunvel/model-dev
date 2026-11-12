"""YOLO text labels (detect, segment, pose) and the dataset YAML (pure conversion).

The format is the de-facto Ultralytics layout (``docs/FORMATS.md`` section 2). This module writes
and reads the text only; it never imports the AGPL Ultralytics package (Development Rule 4).

Line formats, all coordinates normalised 0-1 by the image width and height, class index zero-based:
  detect   ``class xc yc w h``
  segment  ``class x1 y1 x2 y2 ... xn yn``                (at least 3 points)
  pose     ``class xc yc w h  x1 y1 v1  x2 y2 v2 ...``    (v: 0 not labelled, 1 hidden, 2 visible)
"""

from collections.abc import Mapping, Sequence
from typing import Any

import yaml

from studio.formats.geometry import bounds, labelled

TASKS = ("detect", "segment", "pose")


def _n(value: float) -> str:
    text = f"{min(max(value, 0.0), 1.0):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _line(task: str, item: Mapping[str, Any], index: int, width: int, height: int) -> str | None:
    kind, data = item["kind"], item["data"]
    if task == "detect" and kind == "box":
        x, y, w, h = data["x"], data["y"], data["w"], data["h"]
        values = [(x + w / 2) / width, (y + h / 2) / height, w / width, h / height]
    elif task == "segment" and kind == "polygon":
        values = [v for px, py in data["points"] for v in (px / width, py / height)]
    elif task == "segment" and kind == "box":  # a box is a valid 4-corner polygon
        x, y, w, h = data["x"], data["y"], data["w"], data["h"]
        corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        values = [v for px, py in corners for v in (px / width, py / height)]
    elif task == "pose" and kind == "keypoints":
        points = data["points"]
        x0, y0, x1, y1 = bounds(labelled(points))
        w, h = max(x1 - x0, 1.0), max(y1 - y0, 1.0)  # a single point still gets a 1 px box
        box = [(x0 + w / 2) / width, (y0 + h / 2) / height, w / width, h / height]
        out = [str(index), *(_n(v) for v in box)]
        for px, py, v in points:  # visibility is not a coordinate, so it is written as is
            out += [_n(px / width), _n(py / height), str(int(v))] if v else ["0", "0", "0"]
        return " ".join(out)
    else:
        return None
    return " ".join([str(index), *(_n(v) for v in values)])


def export_lines(
    task: str,
    items: Sequence[Mapping[str, Any]],
    class_index: Mapping[int, int],
    width: int,
    height: int,
) -> tuple[list[str], int]:
    """Label lines for one image, and how many annotations this task cannot express."""
    if task not in TASKS:
        raise ValueError(f"Unknown YOLO task '{task}'. Use one of {list(TASKS)}.")
    lines: list[str] = []
    skipped = 0
    for item in items:
        index = class_index.get(item["class_id"])
        line = _line(task, item, index, width, height) if index is not None else None
        if line is None:
            skipped += 1
        else:
            lines.append(line)
    return lines, skipped


def parse_label_text(
    text: str, width: int, height: int, kpt_shape: Sequence[int] | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read one label file. Returns ``(annotations, problems)``.

    Each annotation is ``{"class_index", "kind", "data"}`` in pixels. With ``kpt_shape`` (from the
    dataset YAML) every line is a pose line; without it a 5-number line is a box and a longer one a
    polygon.
    """
    found: list[dict[str, Any]] = []
    problems: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            parts = line.split()
            index = int(parts[0])
            values = [float(v) for v in parts[1:]]
        except ValueError:
            problems.append(f"line {number}: not numbers")
            continue
        if index < 0:
            problems.append(f"line {number}: negative class index")
            continue
        item = _read(index, values, width, height, kpt_shape)
        if item is None:
            problems.append(f"line {number}: {len(values)} numbers do not match any YOLO format")
        else:
            found.append(item)
    return found, problems


def _read(
    index: int, values: list[float], width: int, height: int, kpt_shape: Sequence[int] | None
) -> dict[str, Any] | None:
    if kpt_shape:
        count, dims = int(kpt_shape[0]), int(kpt_shape[1])
        if len(values) != 4 + count * dims:
            return None
        points = []
        for i in range(count):
            chunk = values[4 + i * dims : 4 + (i + 1) * dims]
            visibility = int(chunk[2]) if dims == 3 else 2
            if visibility not in (0, 1, 2):
                return None
            points.append(
                [0, 0, 0] if visibility == 0 else [chunk[0] * width, chunk[1] * height, visibility]
            )
        return {"class_index": index, "kind": "keypoints", "data": {"points": points}}
    if len(values) == 4:
        xc, yc, w, h = values
        return {
            "class_index": index,
            "kind": "box",
            "data": {
                "x": (xc - w / 2) * width,
                "y": (yc - h / 2) * height,
                "w": w * width,
                "h": h * height,
            },
        }
    if len(values) >= 6 and len(values) % 2 == 0:
        pairs = [[values[i] * width, values[i + 1] * height] for i in range(0, len(values), 2)]
        return {"class_index": index, "kind": "polygon", "data": {"points": pairs}}
    return None


def dataset_yaml(
    names: Sequence[str], splits: Sequence[str], kpt_shape: Sequence[int] | None = None
) -> str:
    """The dataset description file. ``splits`` are the split names that have images."""
    document: dict[str, Any] = {"path": "."}
    train = "train" if "train" in splits else splits[0]
    document["train"] = f"images/{train}"
    document["val"] = f"images/{'val' if 'val' in splits else train}"
    if "test" in splits:
        document["test"] = "images/test"
    if kpt_shape:
        document["kpt_shape"] = [int(kpt_shape[0]), int(kpt_shape[1])]
    document["names"] = {i: name for i, name in enumerate(names)}
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
