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
