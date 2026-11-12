"""COCO detection / segmentation / keypoints JSON (pure conversion).

``build`` turns our annotations into one COCO document; ``parse`` reads one back. The round trip is
lossless for what we export: box, polygon and keypoints annotations each come back as the same kind.
Based on the public COCO format description (``docs/FORMATS.md`` section 3).
"""

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from studio.formats.geometry import bounds, labelled, polygon_area


def _r(value: float) -> float:
    return round(float(value), 2)


def build(
    images: Sequence[Mapping[str, Any]], classes: Sequence[Mapping[str, Any]], description: str = ""
) -> dict[str, Any]:
    """One COCO document.

    ``images``: ``{"id", "file_name", "width", "height", "annotations": [{class_id, kind, data}]}``.
    ``classes``: ``{"id", "name", "skeleton"}``. Category ids are our class ids.
    """
    categories = []
    for cls in classes:
        category: dict[str, Any] = {"id": cls["id"], "name": cls["name"], "supercategory": ""}
        skeleton = cls.get("skeleton")
        if skeleton:
            category["keypoints"] = list(skeleton["names"])
            category["skeleton"] = [[a + 1, b + 1] for a, b in skeleton["edges"]]  # COCO is 1-based
        categories.append(category)
    out_images = []
    out_annotations = []
    next_id = 1
    for image in images:
        out_images.append(
            {
                "id": image["id"],
                "file_name": image["file_name"],
                "width": image["width"],
                "height": image["height"],
            }
        )
        for item in image["annotations"]:
            record = _annotation(item)
            record.update({"id": next_id, "image_id": image["id"], "category_id": item["class_id"]})
            next_id += 1
            out_annotations.append(record)
    return {
        "info": {"description": description, "version": "1.0"},
        "licenses": [],
        "images": out_images,
        "annotations": out_annotations,
        "categories": categories,
    }


def _annotation(item: Mapping[str, Any]) -> dict[str, Any]:
    kind, data = item["kind"], item["data"]
    if kind == "box":
        return {
            "bbox": [_r(data["x"]), _r(data["y"]), _r(data["w"]), _r(data["h"])],
            "area": _r(data["w"] * data["h"]),
            "segmentation": [],
            "iscrowd": 0,
        }
    if kind == "polygon":
        points = data["points"]
        x0, y0, x1, y1 = bounds(points)
        return {
            "bbox": [_r(x0), _r(y0), _r(x1 - x0), _r(y1 - y0)],
            "area": _r(polygon_area(points)),
            "segmentation": [[_r(v) for p in points for v in p]],
            "iscrowd": 0,
        }
    points = data["points"]  # keypoints
    placed = labelled(points)
    x0, y0, x1, y1 = bounds(placed)
    return {
        "bbox": [_r(x0), _r(y0), _r(x1 - x0), _r(y1 - y0)],
        "area": _r((x1 - x0) * (y1 - y0)),
        "segmentation": [],
        "iscrowd": 0,
        "keypoints": [value for p in points for value in (_r(p[0]), _r(p[1]), int(p[2]))],
        "num_keypoints": len(placed),
    }


def parse(document: Mapping[str, Any]) -> dict[str, Any]:
    """Read a COCO document.

    Returns ``{"categories": {id: {"name", "skeleton"}}, "images": [{"file_name", "width",
    "height", "annotations": [{"category_id", "kind", "data"}]}], "skipped": [str, ...]}``.
    Annotations we cannot represent (RLE masks) are listed in ``skipped``, never dropped silently.
    """
    if not isinstance(document, Mapping) or not isinstance(document.get("images"), list):
        raise ValueError("This does not look like a COCO file: it has no 'images' list.")
    categories: dict[Any, dict[str, Any]] = {}
    for cat in document.get("categories") or []:
        skeleton = None
        names = cat.get("keypoints")
        if names:
            edges = [[int(a) - 1, int(b) - 1] for a, b in cat.get("skeleton") or []]
            skeleton = {"names": [str(n) for n in names], "edges": edges}
        categories[cat["id"]] = {"name": str(cat["name"]), "skeleton": skeleton}
    by_id: dict[Any, dict[str, Any]] = {}
    images = []
    for image in document["images"]:
        record: dict[str, Any] = {
            "file_name": str(image["file_name"]),
            "width": image.get("width"),
            "height": image.get("height"),
            "annotations": [],
        }
        by_id[image["id"]] = record
        images.append(record)
    skipped: list[str] = []
    for ann in document.get("annotations") or []:
        target = by_id.get(ann.get("image_id"))
        if target is None:
            skipped.append(f"annotation {ann.get('id')}: its image is not in the file")
            continue
        category_id = ann.get("category_id")
        for kind, data in _read(ann, skipped):
            target["annotations"].append({"category_id": category_id, "kind": kind, "data": data})
    return {"categories": categories, "images": images, "skipped": skipped}


def _read(ann: Mapping[str, Any], skipped: list[str]) -> Iterator[tuple[str, dict[str, Any]]]:
    keypoints = ann.get("keypoints")
    segmentation = ann.get("segmentation")
    if keypoints:
        if len(keypoints) % 3:
            skipped.append(f"annotation {ann.get('id')}: keypoints are not x, y, v triples")
            return
        triples = [keypoints[i : i + 3] for i in range(0, len(keypoints), 3)]
        yield "keypoints", {
            "points": [[0, 0, 0] if t[2] == 0 else [t[0], t[1], int(t[2])] for t in triples]
        }
    elif isinstance(segmentation, list) and segmentation:
        for part in segmentation:
            if len(part) < 6 or len(part) % 2:
                skipped.append(f"annotation {ann.get('id')}: a polygon needs at least 3 x, y pairs")
                continue
            yield "polygon", {"points": [[part[i], part[i + 1]] for i in range(0, len(part), 2)]}
    elif isinstance(segmentation, Mapping):
        skipped.append(f"annotation {ann.get('id')}: RLE masks are not supported yet")
    elif ann.get("bbox") and len(ann["bbox"]) == 4:
        x, y, w, h = ann["bbox"]
        yield "box", {"x": x, "y": y, "w": w, "h": h}
    else:
        skipped.append(f"annotation {ann.get('id')}: no box, polygon or keypoints")
