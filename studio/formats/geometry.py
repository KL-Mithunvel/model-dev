"""Small shared geometry helpers for the format converters."""

from collections.abc import Sequence


def bounds(points: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) of ``points``; needs at least one."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def polygon_area(points: Sequence[Sequence[float]]) -> float:
    """Shoelace area (>= 0)."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, [*points[1:], points[0]], strict=True):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def labelled(points: Sequence[Sequence[float]]) -> list[Sequence[float]]:
    """The keypoints that have a position (visibility above 0)."""
    return [p for p in points if p[2] > 0]
