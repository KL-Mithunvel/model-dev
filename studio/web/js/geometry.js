// Pure geometry for the annotator (no DOM). Image space = pixels of the EXIF-oriented image,
// origin top-left. "View" = how the image sits in the stage: { scale, tx, ty } meaning
// screen = image * scale + (tx, ty).

export const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

export const clamp = (value, low, high) => Math.min(Math.max(value, low), high);
export const round2 = (value) => Math.round(value * 100) / 100;

// ---- boxes ----------------------------------------------------------------------------------

/** Box spanned by two corner points in any order, clamped to the image. */
export function boxFromPoints(x0, y0, x1, y1, width, height) {
  const left = clamp(Math.min(x0, x1), 0, width);
  const right = clamp(Math.max(x0, x1), 0, width);
  const top = clamp(Math.min(y0, y1), 0, height);
  const bottom = clamp(Math.max(y0, y1), 0, height);
  return { x: left, y: top, w: right - left, h: bottom - top };
}

/** Move a box by (dx, dy); it stops at the image edges and keeps its size. */
export function moveBox(box, dx, dy, width, height) {
  return {
    x: clamp(box.x + dx, 0, Math.max(0, width - box.w)),
    y: clamp(box.y + dy, 0, Math.max(0, height - box.h)),
    w: box.w,
    h: box.h,
  };
}

/** Position of one of the 8 resize handles. */
export function handlePoint(box, handle) {
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  const right = box.x + box.w;
  const bottom = box.y + box.h;
  const points = {
    nw: [box.x, box.y], n: [cx, box.y], ne: [right, box.y], e: [right, cy],
    se: [right, bottom], s: [cx, bottom], sw: [box.x, bottom], w: [box.x, cy],
  };
  const [x, y] = points[handle];
  return { x, y };
}

/**
 * Drag a handle to the pointer position (px, py). The opposite edges stay put, the box never
 * flips or shrinks below `minSize`, and it stays inside the image.
 */
export function resizeBoxTo(box, handle, px, py, width, height, minSize = 1) {
  let left = box.x;
  let top = box.y;
  let right = box.x + box.w;
  let bottom = box.y + box.h;
  if (handle.includes("w")) left = clamp(px, 0, right - minSize);
  if (handle.includes("e")) right = clamp(px, left + minSize, width);
  if (handle.includes("n")) top = clamp(py, 0, bottom - minSize);
  if (handle.includes("s")) bottom = clamp(py, top + minSize, height);
  return { x: left, y: top, w: right - left, h: bottom - top };
}

/** Keyboard resize: change width/height by (dw, dh) keeping the top-left corner. */
export function resizeBoxBy(box, dw, dh, width, height, minSize = 1) {
  return {
    x: box.x,
    y: box.y,
    w: clamp(box.w + dw, minSize, width - box.x),
    h: clamp(box.h + dh, minSize, height - box.y),
  };
}

/** A box covering `fraction` of the visible image area, centred on (cx, cy), inside the image. */
export function defaultBox(cx, cy, visibleW, visibleH, width, height, fraction = 0.25) {
  const w = Math.max(1, Math.min(width, visibleW * Math.sqrt(fraction)));
  const h = Math.max(1, Math.min(height, visibleH * Math.sqrt(fraction)));
  return moveBox({ x: cx - w / 2, y: cy - h / 2, w, h }, 0, 0, width, height);
}

export const roundBox = (box) => ({ x: round2(box.x), y: round2(box.y), w: round2(box.w), h: round2(box.h) });

// ---- view (zoom and pan) --------------------------------------------------------------------

/** Scale and offset that fit the whole image inside the stage, centred, with a margin. */
export function fitView(stageW, stageH, imageW, imageH, margin = 16) {
  const scale = Math.max(
    0.01,
    Math.min((stageW - 2 * margin) / imageW, (stageH - 2 * margin) / imageH),
  );
  return { scale, tx: (stageW - imageW * scale) / 2, ty: (stageH - imageH * scale) / 2 };
}

export function screenToImage(view, sx, sy) {
  return { x: (sx - view.tx) / view.scale, y: (sy - view.ty) / view.scale };
}

export function imageToScreen(view, x, y) {
  return { x: x * view.scale + view.tx, y: y * view.scale + view.ty };
}

/** Zoom by `factor` keeping the image point under the screen point (sx, sy) fixed. */
export function zoomAt(view, factor, sx, sy, minScale = 0.02, maxScale = 40) {
  const scale = clamp(view.scale * factor, minScale, maxScale);
  const ratio = scale / view.scale;
  return { scale, tx: sx - (sx - view.tx) * ratio, ty: sy - (sy - view.ty) * ratio };
}

export const panBy = (view, dx, dy) => ({ scale: view.scale, tx: view.tx + dx, ty: view.ty + dy });

/** The part of the image currently visible in the stage, in image coordinates. */
export function visibleRect(view, stageW, stageH, imageW, imageH) {
  const topLeft = screenToImage(view, 0, 0);
  const bottomRight = screenToImage(view, stageW, stageH);
  const left = clamp(topLeft.x, 0, imageW);
  const top = clamp(topLeft.y, 0, imageH);
  return {
    x: left,
    y: top,
    w: clamp(bottomRight.x, 0, imageW) - left,
    h: clamp(bottomRight.y, 0, imageH) - top,
  };
}

// ---- polygons -------------------------------------------------------------------------------
// A polygon is an array of [x, y] points (at least 3), implicitly closed.

export const roundPoints = (points) => points.map(([x, y]) => [round2(x), round2(y)]);

export function polygonBounds(points) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of points) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return { minX, minY, maxX, maxY, w: maxX - minX, h: maxY - minY };
}

/** Shoelace area (always >= 0). A bow-tie can have a small or zero area even when it is large. */
export function polygonArea(points) {
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    sum += x1 * y2 - x2 * y1;
  }
  return Math.abs(sum) / 2;
}

export const clampPoint = (x, y, width, height) => [clamp(x, 0, width), clamp(y, 0, height)];

/** Translate every point by (dx, dy); the whole polygon stops at the image edges (no distortion). */
export function movePolygon(points, dx, dy, width, height) {
  const { minX, minY, maxX, maxY } = polygonBounds(points);
  const safeDx = clamp(dx, -minX, width - maxX);
  const safeDy = clamp(dy, -minY, height - maxY);
  return points.map(([x, y]) => [x + safeDx, y + safeDy]);
}

/** Ray casting: is (x, y) inside the polygon? */
export function pointInPolygon(x, y, points) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i];
    const [xj, yj] = points[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function distanceToSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  const t = lengthSquared === 0 ? 0 : clamp(((px - ax) * dx + (py - ay) * dy) / lengthSquared, 0, 1);
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/** The point on the polygon's outline closest to (x, y): { index, x, y, distance }, where `index`
 *  is the segment's first vertex (the new vertex would go after it). */
export function nearestOnPolygon(points, x, y) {
  let best = { index: 0, x: points[0][0], y: points[0][1], distance: Infinity };
  for (let i = 0; i < points.length; i++) {
    const [ax, ay] = points[i];
    const [bx, by] = points[(i + 1) % points.length];
    const dx = bx - ax;
    const dy = by - ay;
    const lengthSquared = dx * dx + dy * dy;
    const t = lengthSquared === 0 ? 0 : clamp(((x - ax) * dx + (y - ay) * dy) / lengthSquared, 0, 1);
    const cx = ax + t * dx;
    const cy = ay + t * dy;
    const distance = Math.hypot(x - cx, y - cy);
    if (distance < best.distance) best = { index: i, x: cx, y: cy, distance };
  }
  return best;
}

export const midpoint = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];

function crossProduct(a, b, c) {
  return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0]);
}

function segmentsCross(a, b, c, d) {
  const d1 = crossProduct(a, b, c);
  const d2 = crossProduct(a, b, d);
  const d3 = crossProduct(c, d, a);
  const d4 = crossProduct(c, d, b);
  return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
}

/** True if two non-adjacent edges properly cross (a "bow-tie"). Touching at a vertex is not a crossing. */
export function polygonSelfIntersects(points) {
  const n = points.length;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (j === i + 1 || (i === 0 && j === n - 1)) continue; // edges that share a vertex
      if (segmentsCross(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n])) return true;
    }
  }
  return false;
}

function simplifyChain(chain, epsilon) {
  if (chain.length < 3) return chain;
  const [ax, ay] = chain[0];
  const [bx, by] = chain[chain.length - 1];
  let farthest = -1;
  let farthestDistance = -1;
  for (let i = 1; i < chain.length - 1; i++) {
    const d = distanceToSegment(chain[i][0], chain[i][1], ax, ay, bx, by);
    if (d > farthestDistance) { farthest = i; farthestDistance = d; }
  }
  if (farthestDistance <= epsilon) return [chain[0], chain[chain.length - 1]];
  const left = simplifyChain(chain.slice(0, farthest + 1), epsilon);
  const right = simplifyChain(chain.slice(farthest), epsilon);
  return [...left.slice(0, -1), ...right];
}

/**
 * Ramer-Douglas-Peucker for a closed polygon: drop points that stay within `epsilon` pixels of the
 * simplified outline. Never returns fewer than `minPoints`; if it cannot simplify, returns the input.
 */
export function simplifyPolygon(points, epsilon, minPoints = 3) {
  if (points.length <= minPoints || epsilon <= 0) return points;
  // Split the ring at point 0 and at the point farthest from it, so both halves are open chains.
  let split = 1;
  let splitDistance = -1;
  for (let i = 1; i < points.length; i++) {
    const d = Math.hypot(points[i][0] - points[0][0], points[i][1] - points[0][1]);
    if (d > splitDistance) { split = i; splitDistance = d; }
  }
  const first = simplifyChain(points.slice(0, split + 1), epsilon);
  const second = simplifyChain([...points.slice(split), points[0]], epsilon);
  const result = [...first.slice(0, -1), ...second.slice(0, -1)];
  return result.length >= minPoints ? result : points;
}

/** A regular polygon with `sides` corners centred at (cx, cy), covering about `fraction` of the view. */
export function defaultPolygon(cx, cy, visibleW, visibleH, width, height, sides = 6, fraction = 0.25) {
  const radius = Math.max(2, (Math.min(visibleW, visibleH) * Math.sqrt(fraction)) / 2);
  const points = [];
  for (let i = 0; i < sides; i++) {
    const angle = (2 * Math.PI * i) / sides - Math.PI / 2;
    points.push([cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)]);
  }
  return movePolygon(points, 0, 0, width, height).map(([x, y]) => clampPoint(x, y, width, height));
}
