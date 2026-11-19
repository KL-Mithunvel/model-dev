"""Turn a segmentation mask into a polygon, with numpy only (no OpenCV dependency).

``mask_to_polygon`` follows the OUTER outline of the one 4-connected blob that contains a seed point,
along pixel edges ("crack following"), so a filled w x h rectangle becomes exactly that rectangle.
The outline is then simplified with Ramer-Douglas-Peucker. Holes are ignored because annotation
polygons are hole-free. Only the seed's own blob is traced; the rest of the mask is never labelled.

Directions are 0 east, 1 south, 2 west, 3 north (y grows downwards). The walk keeps filled pixels on
its RIGHT, so an outer outline runs clockwise on screen (positive shoelace area in this system) and
a hole runs the other way (negative), which is how the two are told apart.
"""

import numpy as np

_STEP = ((1, 0), (0, 1), (-1, 0), (0, -1))


def _ahead(direction: int, x: int, y: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """The pixels (left, right) just beyond corner (x, y) when arriving in ``direction``."""
    if direction == 0:
        return (x, y - 1), (x, y)
    if direction == 1:
        return (x, y), (x - 1, y)
    if direction == 2:
        return (x - 1, y), (x - 1, y - 1)
    return (x - 1, y - 1), (x, y - 1)


def trace_outline(mask: np.ndarray, sx: int, sy: int) -> list[tuple[int, int]]:
    """The closed outline (corner points where it turns) of the blob whose pixel (sx, sy) has an
    empty WEST neighbour. The walk starts up the west edge of that pixel."""
    height, width = mask.shape

    def filled(px: int, py: int) -> bool:
        return 0 <= px < width and 0 <= py < height and bool(mask[py, px])

    x, y, direction = sx, sy + 1, 3
    start = (x, y, direction)
    corners: list[tuple[int, int]] = [(x, y)]
    budget = 4 * int(mask.sum()) + 8  # an outline is never longer than 4 edges per pixel
    while budget:
        budget -= 1
        dx, dy = _STEP[direction]
        x, y = x + dx, y + dy
        left, right = _ahead(direction, x, y)
        if filled(*right):
            new = (direction - 1) % 4 if filled(*left) else direction
        else:
            new = (direction + 1) % 4
        if (x, y, new) == start:
            return corners
        if new != direction:
            corners.append((x, y))
        direction = new
    return corners  # unreachable for a valid mask; returns what was traced rather than looping


def signed_area(points: list[tuple[float, float]]) -> float:
    """Shoelace area; positive for the clockwise-on-screen outlines this module treats as outer."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=True):
        total += x0 * y1 - x1 * y0
    return total / 2


def _rdp(points: np.ndarray, epsilon: float) -> np.ndarray:
    keep = np.zeros(len(points), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        start, segment = points[lo], points[hi] - points[lo]
        length = float(np.hypot(*segment))
        middle = points[lo + 1 : hi] - start
        if length == 0:
            distances = np.hypot(middle[:, 0], middle[:, 1])
        else:
            distances = np.abs(segment[0] * middle[:, 1] - segment[1] * middle[:, 0]) / length
        far = int(np.argmax(distances))
        if distances[far] > epsilon:
            index = lo + 1 + far
            keep[index] = True
            stack.extend([(lo, index), (index, hi)])
    return points[keep]


def drop_collinear(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Remove vertices that lie exactly on the line between their neighbours (the walk's start is one)."""
    count = len(points)
    kept = []
    for i, (x, y) in enumerate(points):
        px, py = points[i - 1]
        nx, ny = points[(i + 1) % count]
        if (x - px) * (ny - y) - (y - py) * (nx - x) != 0:
            kept.append((x, y))
    return kept if len(kept) >= 3 else points


def simplify_ring(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker on a closed ring, split at its two farthest-apart anchors.

    Never returns fewer than 3 points; returns the input unchanged if simplifying would.
    """
    if len(points) <= 3 or epsilon <= 0:
        return points
    array = np.asarray(points, dtype=float)
    anchor = int(np.argmax(np.hypot(*(array - array[0]).T)))
    first_half = _rdp(array[: anchor + 1], epsilon)
    second_half = _rdp(np.vstack([array[anchor:], array[:1]]), epsilon)
    ring = [tuple(p) for p in first_half[:-1]] + [tuple(p) for p in second_half[:-1]]
    return ring if len(ring) >= 3 else points


def mask_to_polygon(
    mask: np.ndarray, seed: tuple[float, float] | None = None, epsilon: float = 1.5
) -> list[list[float]] | None:
    """Polygon ``[[x, y], ...]`` around one blob of ``mask`` (True = object), or None if the mask is
    empty or the blob is a single sliver with no area.

    ``seed`` (x, y) picks the blob; if it is not on the mask, the nearest mask pixel is used. Without
    a seed the first mask pixel in reading order is used.
    """
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 2 or not mask.any():
        return None
    height, width = mask.shape
    ys, xs = np.nonzero(mask)
    if seed is None:
        sx, sy = int(xs[0]), int(ys[0])
    else:
        sx = min(max(int(seed[0]), 0), width - 1)
        sy = min(max(int(seed[1]), 0), height - 1)
        if not mask[sy, sx]:
            nearest = int(np.argmin((xs - sx) ** 2 + (ys - sy) ** 2))
            sx, sy = int(xs[nearest]), int(ys[nearest])
    x = sx
    outline: list[tuple[int, int]] = []
    while True:
        while x > 0 and mask[sy, x - 1]:  # left edge of this run of filled pixels
            x -= 1
        outline = trace_outline(mask, x, sy)
        if signed_area([(float(a), float(b)) for a, b in outline]) > 0:
            break  # an outer outline
        x -= 1  # we traced a hole; step across it to the wall that encloses it
        while x >= 0 and not mask[sy, x]:
            x -= 1
        if x < 0:
            break
    ring = simplify_ring(drop_collinear([(float(a), float(b)) for a, b in outline]), epsilon)
    if len(ring) < 3 or abs(signed_area(ring)) < 1e-9:
        return None
    return [[round(a, 2), round(b, 2)] for a, b in ring]
