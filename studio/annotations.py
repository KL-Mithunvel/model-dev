"""Validation of annotations (pure logic, no I/O).

Coordinates are pixels of the EXIF-oriented image, origin top-left. Every function raises
``AnnotationError`` with a message that says what is wrong and which annotation (1-based).
"""

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

KINDS = ("box", "polygon", "keypoints")
VISIBILITY = (0, 1, 2)  # 0 not labelled, 1 labelled but hidden, 2 visible


class AnnotationError(ValueError):
    """An annotation (or the set of annotations) is not acceptable."""


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnnotationError(f"{what} must be a finite number.")
    try:
        finite = math.isfinite(value)  # raises OverflowError for integers beyond float range
    except OverflowError:
        finite = False
    if not finite:
        raise AnnotationError(f"{what} must be a finite number.")
    return float(value)


def _inside(value: float, limit: float, tolerance: float, what: str) -> float:
    if value < -tolerance or value > limit + tolerance:
        raise AnnotationError(f"{what} ({value:g}) is outside the image (0 to {limit:g}).")
    return min(max(value, 0.0), limit)  # clamp the tolerated overshoot


def _round(value: float) -> float:
    return round(value, 2)


def _only_keys(data: Mapping[str, Any], allowed: set[str], where: str) -> None:
    extra = set(data) - allowed
    if extra:
        raise AnnotationError(f"{where}: unexpected field(s) {sorted(extra)}.")
    missing = allowed - set(data)
    if missing:
        raise AnnotationError(f"{where}: missing field(s) {sorted(missing)}.")


def _validate_box(data, width, height, limits, where) -> dict[str, float]:
    _only_keys(data, {"x", "y", "w", "h"}, where)
    tol = limits["coord_tolerance_px"]
    x, y = _number(data["x"], f"{where}: x"), _number(data["y"], f"{where}: y")
    w, h = _number(data["w"], f"{where}: w"), _number(data["h"], f"{where}: h")
    if w < limits["min_box_px"] or h < limits["min_box_px"]:
        raise AnnotationError(
            f"{where}: a box must be at least {limits['min_box_px']} px wide and tall."
        )
    x0, y0 = (
        _inside(x, width, tol, f"{where}: left edge"),
        _inside(y, height, tol, f"{where}: top edge"),
    )
    x1, y1 = (
        _inside(x + w, width, tol, f"{where}: right edge"),
        _inside(y + h, height, tol, f"{where}: bottom edge"),
    )
    if x1 - x0 < limits["min_box_px"] or y1 - y0 < limits["min_box_px"]:
        raise AnnotationError(
            f"{where}: a box must be at least {limits['min_box_px']} px wide and tall."
        )
    return {"x": _round(x0), "y": _round(y0), "w": _round(x1 - x0), "h": _round(y1 - y0)}


def _points(data, size, width, height, limits, where) -> list[list[float]]:
    points = data["points"]
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
        raise AnnotationError(f"{where}: points must be a list.")
    if len(points) > limits["max_points"]:
        raise AnnotationError(f"{where}: more than {limits['max_points']} points.")
    out = []
    for index, point in enumerate(points, start=1):
        if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) != size:
            raise AnnotationError(f"{where}: point {index} must have {size} numbers.")
        out.append([_number(v, f"{where}: point {index}") for v in point])
    return out


def _validate_polygon(data, width, height, limits, where) -> dict[str, list[list[float]]]:
    _only_keys(data, {"points"}, where)
    points = _points(data, 2, width, height, limits, where)
    if len(points) < 3:
        raise AnnotationError(f"{where}: a polygon needs at least 3 points.")
    tol = limits["coord_tolerance_px"]
    cleaned = [
        [
            _round(_inside(x, width, tol, f"{where}: point {i} x")),
            _round(_inside(y, height, tol, f"{where}: point {i} y")),
        ]
        for i, (x, y) in enumerate(points, start=1)
    ]
    area = (
        abs(
            sum(
                x1 * y2 - x2 * y1
                for (x1, y1), (x2, y2) in zip(cleaned, cleaned[1:] + cleaned[:1], strict=True)
            )
        )
        / 2
    )
    if area < limits["min_polygon_area_px"]:
        raise AnnotationError(f"{where}: the polygon is flat or too small (area {area:g} px²).")
    return {"points": cleaned}


def _validate_keypoints(
    data, width, height, limits, where, skeleton
) -> dict[str, list[list[float]]]:
    _only_keys(data, {"points"}, where)
    points = _points(data, 3, width, height, limits, where)
    if not points:
        raise AnnotationError(f"{where}: at least one point is required.")
    if skeleton is not None and len(points) != len(skeleton["names"]):
        expected = len(skeleton["names"])
        raise AnnotationError(
            f"{where}: this class has {expected} keypoints but {len(points)} were sent."
        )
    tol = limits["coord_tolerance_px"]
    cleaned = []
    for i, (x, y, v) in enumerate(points, start=1):
        if v not in VISIBILITY:
            raise AnnotationError(f"{where}: point {i} visibility must be 0, 1 or 2.")
        if v == 0:
            cleaned.append([0.0, 0.0, 0])  # position is meaningless when not labelled
            continue
        cleaned.append(
            [
                _round(_inside(x, width, tol, f"{where}: point {i} x")),
                _round(_inside(y, height, tol, f"{where}: point {i} y")),
                int(v),
            ]
        )
    if all(point[2] == 0 for point in cleaned):
        raise AnnotationError(f"{where}: at least one keypoint must be labelled.")
    return {"points": cleaned}


def validate_annotation(
    item: Mapping[str, Any],
    index: int,
    width: int,
    height: int,
    limits: Mapping[str, Any],
    skeleton: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the cleaned annotation ``{"kind", "data"}`` or raise ``AnnotationError``.

    ``index`` is 1-based and only used in messages. ``skeleton`` is the class's skeleton, if any.
    """
    where = f"Annotation {index}"
    kind = item.get("kind")
    data = item.get("data")
    if kind not in KINDS:
        raise AnnotationError(f"{where}: kind must be one of {list(KINDS)}.")
    if not isinstance(data, Mapping):
        raise AnnotationError(f"{where}: data must be an object.")
    if kind == "box":
        cleaned = _validate_box(data, width, height, limits, where)
    elif kind == "polygon":
        cleaned = _validate_polygon(data, width, height, limits, where)
    else:
        cleaned = _validate_keypoints(data, width, height, limits, where, skeleton)
    return {"kind": kind, "data": cleaned}


def validate_set(
    items: Sequence[Mapping[str, Any]], marked_empty: bool, limits: Mapping[str, Any]
) -> None:
    """Rules about the whole set of annotations of one image."""
    if len(items) > limits["max_per_image"]:
        raise AnnotationError(f"An image can have at most {limits['max_per_image']} annotations.")
    if marked_empty and items:
        raise AnnotationError("An image with annotations cannot be marked as having no objects.")


def validate_skeleton(skeleton: Any, max_keypoints: int, name_max: int) -> dict[str, Any]:
    """Return the cleaned skeleton ``{"names": [...], "edges": [[i, j], ...]}`` or raise.

    Names are trimmed, non-empty, unique ignoring case; edges join two different points
    (0-based indexes into ``names``) and are stored once, smaller index first.
    """
    if not isinstance(skeleton, Mapping) or set(skeleton) - {"names", "edges"}:
        raise AnnotationError("A skeleton is an object with 'names' and 'edges'.")
    names = skeleton.get("names")
    edges = skeleton.get("edges", [])
    if not isinstance(names, Sequence) or isinstance(names, (str, bytes)) or not names:
        raise AnnotationError("A skeleton needs at least one point name.")
    if len(names) > max_keypoints:
        raise AnnotationError(f"A skeleton can have at most {max_keypoints} points.")
    cleaned_names: list[str] = []
    seen: set[str] = set()
    for index, name in enumerate(names, start=1):
        if not isinstance(name, str) or not " ".join(name.split()):
            raise AnnotationError(f"Skeleton point {index} needs a name.")
        text = " ".join(name.split())
        if len(text) > name_max:
            raise AnnotationError(
                f"Skeleton point {index}: name is longer than {name_max} characters."
            )
        if text.casefold() in seen:
            raise AnnotationError(f"Skeleton point name '{text}' is used twice.")
        seen.add(text.casefold())
        cleaned_names.append(text)
    if not isinstance(edges, Sequence) or isinstance(edges, (str, bytes)):
        raise AnnotationError("Skeleton edges must be a list.")
    cleaned_edges: list[list[int]] = []
    for edge in edges:
        if (
            not isinstance(edge, Sequence)
            or isinstance(edge, (str, bytes))
            or len(edge) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) for v in edge)
        ):
            raise AnnotationError("Each skeleton edge must be two point numbers.")
        a, b = sorted(edge)
        if a < 0 or b >= len(cleaned_names) or a == b:
            raise AnnotationError("A skeleton edge must join two different points of the skeleton.")
        if [a, b] not in cleaned_edges:
            cleaned_edges.append([a, b])
    return {"names": cleaned_names, "edges": cleaned_edges}


def dumps(data: Mapping[str, Any]) -> str:
    """Stable JSON for storage."""
    return json.dumps(data, separators=(",", ":"), sort_keys=True)
