"""Label Studio JSON tasks (pure conversion): rectangles, polygons and keypoints.

Structure from the public Label Studio pages (``docs/FORMATS.md`` section 5). Coordinates are
PERCENTAGES of the image size. A keypoint set is a parent ``rectanglelabels`` result (our class)
plus one ``keypointlabels`` child per labelled point, linked by ``parentID``; the child label is
the point name. Known losses, reported by ``build``: Label Studio has no visibility flag, so
"hidden" points (v = 1) come back as visible (v = 2). Rotated rectangles are skipped on import.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from studio.formats.geometry import bounds, labelled

KEYPOINT_RADIUS_PCT = 0.3  # `width` of a keypoint; its meaning is unverified, so we never read it


class LabelStudioError(ValueError):
    """The JSON cannot be read as Label Studio tasks."""


def _pct(value: float, size: float) -> float:
    return round(value / size * 100.0, 4)


def labeling_config(classes: Sequence[Mapping[str, Any]]) -> str:
    """A matching labeling config so the tasks open in Label Studio without setup."""

    def esc(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    names = [esc(c["name"]) for c in classes]
    points: list[str] = []
    for cls in classes:
        for point in (cls.get("skeleton") or {}).get("names", []):
            if esc(point) not in points:
                points.append(esc(point))

    def group(tag: str, name: str, items: list[str]) -> str:
        inner = "".join(f'<Label value="{n}"/>' for n in items)
        return f'  <{tag} name="{name}" toName="image">{inner}</{tag}>\n'

    text = '<View>\n  <Image name="image" value="$image"/>\n'
    text += group("RectangleLabels", "box", names) + group("PolygonLabels", "polygon", names)
    if points:
        text += group("KeyPointLabels", "keypoint", points)
    return text + "</View>\n"


def build(
    images: Sequence[Mapping[str, Any]], classes: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return ``(tasks, notes)``; ``notes`` lists what the format could not carry."""
    names = {c["id"]: c for c in classes}
    tasks = []
    hidden = 0
    counter = 0

    def new_id() -> str:
        nonlocal counter
        counter += 1
        return f"r{counter}"

    for number, image in enumerate(images, start=1):
        w, h = float(image["width"]), float(image["height"])
        base = {
            "to_name": "image",
            "original_width": image["width"],
            "original_height": image["height"],
            "image_rotation": 0,
        }
        results: list[dict[str, Any]] = []
        for item in image["annotations"]:
            kind, data = item["kind"], item["data"]
            cls = names[item["class_id"]]
            if kind == "box":
                results.append(_rect(new_id(), cls["name"], data, w, h, base))
            elif kind == "polygon":
                results.append(
                    {
                        "id": new_id(),
                        "type": "polygonlabels",
                        "from_name": "polygon",
                        "value": {
                            "points": [[_pct(x, w), _pct(y, h)] for x, y in data["points"]],
                            "polygonlabels": [cls["name"]],
                        },
                        **base,
                    }
                )
            else:
                placed = labelled(data["points"])
                x0, y0, x1, y1 = bounds(placed)
                parent = new_id()
                results.append(
                    _rect(
                        parent,
                        cls["name"],
                        {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0},
                        w,
                        h,
                        base,
                    )
                )
                point_names = cls["skeleton"]["names"]
                for index, (x, y, v) in enumerate(data["points"]):
                    if not v:
                        continue
                    hidden += v == 1
                    results.append(
                        {
                            "id": new_id(),
                            "type": "keypointlabels",
                            "from_name": "keypoint",
                            "parentID": parent,
                            "value": {
                                "x": _pct(x, w),
                                "y": _pct(y, h),
                                "width": KEYPOINT_RADIUS_PCT,
                                "keypointlabels": [point_names[index]],
                            },
                            **base,
                        }
                    )
        tasks.append(
            {
                "id": number,
                "data": {"image": image["file_name"]},
                "annotations": [
                    {"id": number, "was_cancelled": False, "ground_truth": False, "result": results}
                ],
            }
        )
    notes = []
    if hidden:
        notes.append(
            f"{hidden} hidden keypoint(s) will come back as visible "
            "(Label Studio has no visibility flag)"
        )
    return tasks, notes


def _rect(rid: str, label: str, box: Mapping[str, float], w: float, h: float, base: dict[str, Any]):
    return {
        "id": rid,
        "type": "rectanglelabels",
        "from_name": "box",
        "value": {
            "x": _pct(box["x"], w),
            "y": _pct(box["y"], h),
            "width": _pct(box["w"], w),
            "height": _pct(box["h"], h),
            "rotation": 0,
            "rectanglelabels": [label],
        },
        **base,
    }


def parse(
    document: Any, size_of: Callable[[str], tuple[int, int] | None] | None = None
) -> dict[str, Any]:
    """Read Label Studio tasks (the full JSON export: a list of tasks).

    Returns ``{"images": [{"file_name", "width", "height", "annotations": [{"label", "kind",
    "data"}]}], "skipped": [str, ...]}``. Keypoint sets come back as kind ``"named_keypoints"``
    with ``data = {"points": [[name, x, y], ...]}``; the importer orders them by the class skeleton.
    ``size_of(file_name)`` supplies the pixel size when a result has no ``original_width``.
    """
    if not isinstance(document, list):
        raise LabelStudioError("Label Studio's JSON export is a list of tasks.")
    images = []
    skipped: list[str] = []
    for task in document:
        if not isinstance(task, Mapping) or not isinstance(task.get("data"), Mapping):
            skipped.append("an item without a 'data' object was ignored")
            continue
        source = _image_reference(task["data"])
        if not source:
            skipped.append(f"task {task.get('id')}: no image reference in 'data'")
            continue
        annotation = next(
            (
                a
                for a in task.get("annotations") or []
                if isinstance(a, Mapping) and not a.get("was_cancelled")
            ),
            None,
        )
        if annotation is None:
            continue
        record: dict[str, Any] = {
            "file_name": source,
            "width": None,
            "height": None,
            "annotations": [],
        }
        record["fallback"] = size_of(source) if size_of else None
        _read_results(annotation.get("result") or [], record, skipped, source)
        images.append(record)
    return {"images": images, "skipped": skipped}


def _read_results(results: list[Any], record: dict[str, Any], skipped: list[str], source: str):
    children: dict[str, list[Mapping[str, Any]]] = {}
    parents: list[Mapping[str, Any]] = []
    for item in results:
        if not isinstance(item, Mapping) or not isinstance(item.get("value"), Mapping):
            continue
        if item.get("original_width") and not record["width"]:
            record["width"], record["height"] = item["original_width"], item.get("original_height")
        if item.get("type") == "keypointlabels":
            children.setdefault(str(item.get("parentID")), []).append(item)
        else:
            parents.append(item)
    used: set[str] = set()
    for item in parents:
        value, kind = item["value"], item.get("type")
        try:
            if kind == "rectanglelabels":
                label = value["rectanglelabels"][0]
                if value.get("rotation"):
                    raise ValueError("rotated rectangles are not supported")
                w, h = _size(item, record)
                kids = children.get(str(item.get("id")))
                if kids:
                    used.add(str(item.get("id")))
                    points = [
                        [
                            k["value"]["keypointlabels"][0],
                            k["value"]["x"] / 100 * w,
                            k["value"]["y"] / 100 * h,
                        ]
                        for k in kids
                    ]
                    record["annotations"].append(
                        {"label": label, "kind": "named_keypoints", "data": {"points": points}}
                    )
                else:
                    data = {
                        "x": value["x"] / 100 * w,
                        "y": value["y"] / 100 * h,
                        "w": value["width"] / 100 * w,
                        "h": value["height"] / 100 * h,
                    }
                    record["annotations"].append({"label": label, "kind": "box", "data": data})
            elif kind == "polygonlabels":
                w, h = _size(item, record)
                points = [[x / 100 * w, y / 100 * h] for x, y in value["points"]]
                if len(points) < 3:
                    raise ValueError("a polygon needs at least 3 points")
                record["annotations"].append(
                    {
                        "label": value["polygonlabels"][0],
                        "kind": "polygon",
                        "data": {"points": points},
                    }
                )
            else:
                skipped.append(f"{source}: a '{kind}' result is not supported yet and was skipped")
        except (KeyError, IndexError, TypeError, ValueError) as error:
            skipped.append(f"{source}: {kind} {error or 'is incomplete'}")
    orphans = sum(len(v) for k, v in children.items() if k not in used)
    if orphans:
        skipped.append(f"{source}: {orphans} keypoint(s) without a parent rectangle were skipped")


def _size(item: Mapping[str, Any], record: Mapping[str, Any]) -> tuple[float, float]:
    fallback = record.get("fallback") or (None, None)
    w = item.get("original_width") or record.get("width") or fallback[0]
    h = item.get("original_height") or record.get("height") or fallback[1]
    if not w or not h:
        raise ValueError(
            "has no original_width / original_height, so percentages cannot be converted"
        )
    return float(w), float(h)


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff")


def _image_reference(data: Mapping[str, Any]) -> str | None:
    """The task's image: the ``image`` field, else the first value that looks like an image file."""
    value = data.get("image")
    if isinstance(value, str) and value:
        return value
    strings = [v for v in data.values() if isinstance(v, str) and v]
    for candidate in strings:
        if candidate.lower().split("?")[0].endswith(IMAGE_SUFFIXES):
            return candidate
    return strings[0] if strings else None
