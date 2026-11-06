import assert from "node:assert/strict";
import { test } from "node:test";

import {
  boxFromPoints, clamp, defaultBox, fitView, handlePoint, HANDLES, imageToScreen, moveBox,
  panBy, resizeBoxBy, resizeBoxTo, screenToImage, visibleRect, zoomAt,
} from "../../studio/web/js/geometry.js";

const W = 200;
const H = 100;
const box = { x: 40, y: 30, w: 60, h: 40 };

test("boxFromPoints accepts corners in any order and clamps to the image", () => {
  assert.deepEqual(boxFromPoints(50, 60, 10, 20, W, H), { x: 10, y: 20, w: 40, h: 40 });
  assert.deepEqual(boxFromPoints(-30, -5, 500, 300, W, H), { x: 0, y: 0, w: W, h: H });
  assert.deepEqual(boxFromPoints(5, 5, 5, 5, W, H), { x: 5, y: 5, w: 0, h: 0 });
});

test("moveBox keeps size and stops at every edge", () => {
  assert.deepEqual(moveBox(box, 10, -5, W, H), { x: 50, y: 25, w: 60, h: 40 });
  assert.deepEqual(moveBox(box, -999, -999, W, H), { x: 0, y: 0, w: 60, h: 40 });
  assert.deepEqual(moveBox(box, 999, 999, W, H), { x: 140, y: 60, w: 60, h: 40 });
});

test("handlePoint gives the 8 handle positions", () => {
  assert.deepEqual(HANDLES.length, 8);
  assert.deepEqual(handlePoint(box, "nw"), { x: 40, y: 30 });
  assert.deepEqual(handlePoint(box, "se"), { x: 100, y: 70 });
  assert.deepEqual(handlePoint(box, "n"), { x: 70, y: 30 });
  assert.deepEqual(handlePoint(box, "w"), { x: 40, y: 50 });
});

test("resizeBoxTo moves only the dragged edges", () => {
  assert.deepEqual(resizeBoxTo(box, "e", 150, 999, W, H), { x: 40, y: 30, w: 110, h: 40 });
  assert.deepEqual(resizeBoxTo(box, "nw", 10, 5, W, H), { x: 10, y: 5, w: 90, h: 65 });
  assert.deepEqual(resizeBoxTo(box, "s", 0, 90, W, H), { x: 40, y: 30, w: 60, h: 60 });
});

test("resizeBoxTo never flips, never shrinks below the minimum, never leaves the image", () => {
  const dragPastOpposite = resizeBoxTo(box, "e", 10, 0, W, H, 4);
  assert.deepEqual(dragPastOpposite, { x: 40, y: 30, w: 4, h: 40 });
  assert.deepEqual(resizeBoxTo(box, "w", 500, 0, W, H, 4), { x: 96, y: 30, w: 4, h: 40 });
  assert.deepEqual(resizeBoxTo(box, "se", 9999, 9999, W, H), { x: 40, y: 30, w: 160, h: 70 });
  assert.deepEqual(resizeBoxTo(box, "nw", -50, -50, W, H), { x: 0, y: 0, w: 100, h: 70 });
});

test("every handle keeps the box valid for any pointer position", () => {
  for (const handle of HANDLES) {
    for (const [px, py] of [[-1e6, -1e6], [1e6, 1e6], [70, 50], [0, 0], [W, H], [41, 31]]) {
      const r = resizeBoxTo(box, handle, px, py, W, H, 2);
      assert.ok(r.w >= 2 && r.h >= 2, `${handle} ${px},${py}`);
      assert.ok(r.x >= 0 && r.y >= 0 && r.x + r.w <= W && r.y + r.h <= H, `${handle} ${px},${py}`);
    }
  }
});

test("resizeBoxBy keeps the top-left corner and stays inside", () => {
  assert.deepEqual(resizeBoxBy(box, 5, -5, W, H), { x: 40, y: 30, w: 65, h: 35 });
  assert.deepEqual(resizeBoxBy(box, -999, -999, W, H, 3), { x: 40, y: 30, w: 3, h: 3 });
  assert.deepEqual(resizeBoxBy(box, 999, 999, W, H), { x: 40, y: 30, w: 160, h: 70 });
});

test("defaultBox is centred, inside the image, and about a quarter of the visible area", () => {
  const made = defaultBox(100, 50, 200, 100, W, H);
  assert.ok(Math.abs(made.w * made.h - 0.25 * 200 * 100) < 1);
  assert.ok(Math.abs(made.x + made.w / 2 - 100) < 1e-9);
  const corner = defaultBox(0, 0, 200, 100, W, H);
  assert.ok(corner.x >= 0 && corner.y >= 0);
});

test("fitView centres the image and leaves the margin", () => {
  const view = fitView(1000, 600, 500, 250, 20);
  assert.ok(Math.abs(view.scale - 1.92) < 1e-9); // limited by the width: (1000 - 40) / 500
  const topLeft = imageToScreen(view, 0, 0);
  const bottomRight = imageToScreen(view, 500, 250);
  assert.ok(topLeft.x >= 20 - 1e-9 && topLeft.y >= 20 - 1e-9);
  assert.ok(Math.abs(topLeft.x - (1000 - bottomRight.x)) < 1e-9); // horizontally centred
  assert.ok(Math.abs(topLeft.y - (600 - bottomRight.y)) < 1e-9); // vertically centred
});

test("screenToImage and imageToScreen are inverses", () => {
  const view = { scale: 2.5, tx: -30, ty: 17 };
  const there = imageToScreen(view, 44.4, 12.3);
  const back = screenToImage(view, there.x, there.y);
  assert.ok(Math.abs(back.x - 44.4) < 1e-9 && Math.abs(back.y - 12.3) < 1e-9);
});

test("zoomAt keeps the image point under the cursor fixed and respects the limits", () => {
  const view = { scale: 1, tx: 10, ty: 20 };
  const before = screenToImage(view, 300, 200);
  const zoomed = zoomAt(view, 2, 300, 200);
  const after = screenToImage(zoomed, 300, 200);
  assert.ok(Math.abs(before.x - after.x) < 1e-9 && Math.abs(before.y - after.y) < 1e-9);
  assert.equal(zoomAt(view, 1e9, 0, 0, 0.1, 8).scale, 8);
  assert.equal(zoomAt(view, 1e-9, 0, 0, 0.1, 8).scale, 0.1);
});

test("panBy and visibleRect", () => {
  assert.deepEqual(panBy({ scale: 2, tx: 1, ty: 2 }, 5, -5), { scale: 2, tx: 6, ty: -3 });
  const rect = visibleRect({ scale: 1, tx: 50, ty: 50 }, 100, 100, 200, 200);
  assert.deepEqual(rect, { x: 0, y: 0, w: 50, h: 50 }); // only the top-left quarter shows
});

test("clamp", () => {
  assert.equal(clamp(5, 0, 3), 3);
  assert.equal(clamp(-1, 0, 3), 0);
  assert.equal(clamp(2, 0, 3), 2);
});
