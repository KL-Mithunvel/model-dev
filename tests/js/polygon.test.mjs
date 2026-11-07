import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addPolygon, deleteAnnotations, duplicateAnnotations, emptyState, insertVertex, makeIdFactory,
  moveAnnotations, moveVertex, removeVertex, setClass, setMarkedEmpty, simplifyAnnotation,
} from "../../studio/web/js/editor.js";
import {
  clampPoint, defaultPolygon, distanceToSegment, midpoint, movePolygon, nearestOnPolygon,
  pointInPolygon, polygonArea, polygonBounds, polygonSelfIntersects, simplifyPolygon,
} from "../../studio/web/js/geometry.js";
import { createHistory } from "../../studio/web/js/history.js";

const W = 200;
const H = 100;
const square = [[10, 10], [60, 10], [60, 60], [10, 60]];
const approx = (a, b, tolerance = 1e-9) => Math.abs(a - b) <= tolerance;

function deepFreeze(value) {
  if (value && typeof value === "object") {
    Object.freeze(value);
    Object.values(value).forEach(deepFreeze);
  }
  return value;
}

// ---- geometry ---------------------------------------------------------------------------------

test("polygonBounds and polygonArea", () => {
  assert.deepEqual(polygonBounds(square), { minX: 10, minY: 10, maxX: 60, maxY: 60, w: 50, h: 50 });
  assert.equal(polygonArea(square), 2500);
  assert.equal(polygonArea([...square].reverse()), 2500); // orientation does not matter
  assert.equal(polygonArea([[0, 0], [10, 0], [0, 10]]), 50);
  assert.equal(polygonArea([[0, 0], [10, 0], [20, 0]]), 0); // flat
});

test("movePolygon moves the whole shape rigidly and stops at the image edges", () => {
  assert.deepEqual(movePolygon(square, 5, 5, W, H), [[15, 15], [65, 15], [65, 65], [15, 65]]);
  const pushedLeft = movePolygon(square, -999, 0, W, H);
  assert.deepEqual(pushedLeft[0], [0, 10]); // the left-most point reaches the edge...
  assert.deepEqual(pushedLeft[1], [50, 10]); // ...and the shape keeps its size (not squashed)
  const pushedCorner = movePolygon(square, 999, 999, W, H);
  assert.deepEqual(pushedCorner[2], [W, H]);
  assert.equal(polygonArea(pushedCorner), 2500);
});

test("clampPoint", () => {
  assert.deepEqual(clampPoint(-5, 500, W, H), [0, H]);
  assert.deepEqual(clampPoint(20, 30, W, H), [20, 30]);
});

test("pointInPolygon handles a concave L-shape", () => {
  const ell = [[0, 0], [60, 0], [60, 20], [20, 20], [20, 60], [0, 60]];
  assert.equal(pointInPolygon(10, 10, ell), true);
  assert.equal(pointInPolygon(50, 10, ell), true);
  assert.equal(pointInPolygon(10, 50, ell), true);
  assert.equal(pointInPolygon(40, 40, ell), false); // in the notch
  assert.equal(pointInPolygon(-1, 10, ell), false);
  assert.equal(pointInPolygon(30, 30, square), true);
  assert.equal(pointInPolygon(5, 5, square), false);
});

test("distanceToSegment: perpendicular, past the ends, degenerate", () => {
  assert.equal(distanceToSegment(5, 3, 0, 0, 10, 0), 3);
  assert.equal(distanceToSegment(-4, 3, 0, 0, 10, 0), 5); // nearest is the endpoint (0,0)
  assert.equal(distanceToSegment(13, 4, 0, 0, 10, 0), 5);
  assert.equal(distanceToSegment(3, 4, 0, 0, 0, 0), 5); // zero-length segment
});

test("nearestOnPolygon finds the edge (including the closing edge) and the closest point", () => {
  const top = nearestOnPolygon(square, 35, 4);
  assert.equal(top.index, 0);
  assert.ok(approx(top.x, 35) && approx(top.y, 10) && approx(top.distance, 6));
  const closing = nearestOnPolygon(square, 4, 35); // last vertex -> first vertex edge
  assert.equal(closing.index, 3);
  assert.ok(approx(closing.x, 10) && approx(closing.y, 35));
  assert.deepEqual(midpoint([0, 0], [10, 20]), [5, 10]);
});

test("polygonSelfIntersects: bow-ties cross, ordinary shapes do not", () => {
  assert.equal(polygonSelfIntersects(square), false);
  assert.equal(polygonSelfIntersects([[0, 0], [10, 0], [0, 10]]), false);
  assert.equal(polygonSelfIntersects([[0, 0], [10, 10], [10, 0], [0, 10]]), true); // bow-tie
  const pentagram = [0, 2, 4, 1, 3].map((k) => [50 + 40 * Math.cos((2 * Math.PI * k) / 5), 50 + 40 * Math.sin((2 * Math.PI * k) / 5)]);
  assert.equal(polygonSelfIntersects(pentagram), true);
  const ell = [[0, 0], [60, 0], [60, 20], [20, 20], [20, 60], [0, 60]];
  assert.equal(polygonSelfIntersects(ell), false); // concave is fine
  const circle = Array.from({ length: 400 }, (_, i) => [100 + 90 * Math.cos((2 * Math.PI * i) / 400), 100 + 90 * Math.sin((2 * Math.PI * i) / 400)]);
  assert.equal(polygonSelfIntersects(circle), false);
});

test("simplifyPolygon removes collinear points and tiny noise but keeps the corners", () => {
  const withMidpoints = [[10, 10], [35, 10], [60, 10], [60, 35], [60, 60], [35, 60], [10, 60], [10, 35]];
  const simple = simplifyPolygon(withMidpoints, 0.5);
  assert.equal(simple.length, 4);
  for (const corner of square) assert.ok(simple.some(([x, y]) => x === corner[0] && y === corner[1]));
  assert.equal(simplifyPolygon(withMidpoints, 0), withMidpoints); // epsilon 0: untouched
  assert.equal(simplifyPolygon(square, 100), square); // everything is within epsilon, but only 2 points would remain: the input comes back
});

test("simplifyPolygon never returns fewer than 3 points", () => {
  const triangleWithNoise = [[0, 0], [20, 0.2], [40, 0], [20, 30], [10, 15], [30, 15]];
  const out = simplifyPolygon(triangleWithNoise, 50);
  assert.ok(out.length >= 3);
  const tri = [[0, 0], [10, 0], [0, 10]];
  assert.equal(simplifyPolygon(tri, 1000), tri);
});

test("simplifyPolygon property: every original point stays within epsilon of the result's outline", () => {
  let seed = 7;
  const random = () => ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296);
  for (let round = 0; round < 25; round++) {
    const n = 20 + Math.floor(random() * 80);
    const noisy = Array.from({ length: n }, (_, i) => {
      const angle = (2 * Math.PI * i) / n;
      const radius = 40 + random() * 3;
      return [100 + radius * Math.cos(angle), 100 + radius * Math.sin(angle)];
    });
    const epsilon = 1 + random() * 4;
    const simple = simplifyPolygon(noisy, epsilon);
    assert.ok(simple.length >= 3 && simple.length <= noisy.length);
    for (const [x, y] of noisy) {
      const distance = nearestOnPolygon(simple, x, y).distance;
      assert.ok(distance <= epsilon + 1e-6, `round ${round}: ${distance} > ${epsilon}`);
    }
  }
});

test("defaultPolygon has the requested corners, inside the image, around the centre", () => {
  const hex = defaultPolygon(100, 50, 200, 100, W, H);
  assert.equal(hex.length, 6);
  assert.ok(hex.every(([x, y]) => x >= 0 && x <= W && y >= 0 && y <= H));
  const bounds = polygonBounds(hex);
  assert.ok(Math.abs((bounds.minX + bounds.maxX) / 2 - 100) < 1);
  const nearCorner = defaultPolygon(0, 0, 200, 100, W, H); // a view centred ON the corner: pushed inside
  assert.ok(nearCorner.every(([x, y]) => x >= 0 && x <= W && y >= 0 && y <= H));
  assert.ok(polygonArea(nearCorner) > 0 && polygonArea(nearCorner) > 0.5 * polygonArea(hex)); // not squashed
  assert.equal(defaultPolygon(100, 50, 200, 100, W, H, 3).length, 3);
});

// ---- editor -----------------------------------------------------------------------------------

test("addPolygon rounds points and clears 'no objects'", () => {
  const start = setMarkedEmpty(emptyState(), true);
  const state = addPolygon(start, "a1", 2, [[10.123, 10.456], [60.999, 10], [60, 60.001]]);
  assert.deepEqual(state.annotations[0].data.points, [[10.12, 10.46], [61, 10], [60, 60]]);
  assert.equal(state.annotations[0].kind, "polygon");
  assert.equal(state.marked_empty, false);
});

test("moveVertex, insertVertex and removeVertex do what they say and never touch their input", () => {
  let state = deepFreeze(addPolygon(emptyState(), "a1", 1, square));
  state = deepFreeze(moveVertex(state, "a1", 2, 70, 80, W, H));
  assert.deepEqual(state.annotations[0].data.points[2], [70, 80]);
  state = deepFreeze(moveVertex(state, "a1", 0, -50, 999, W, H)); // clamped to the image
  assert.deepEqual(state.annotations[0].data.points[0], [0, H]);
  state = deepFreeze(insertVertex(state, "a1", 1, 65, 30, W, H));
  assert.equal(state.annotations[0].data.points.length, 5);
  assert.deepEqual(state.annotations[0].data.points[2], [65, 30]); // right after vertex 1
  state = deepFreeze(removeVertex(state, "a1", 2));
  assert.equal(state.annotations[0].data.points.length, 4);
});

test("removeVertex keeps the minimum of 3 points (state returned unchanged)", () => {
  const tri = addPolygon(emptyState(), "a1", 1, [[0, 0], [10, 0], [0, 10]]);
  assert.equal(removeVertex(tri, "a1", 0), tri);
  assert.equal(removeVertex(tri, "missing", 0), tri);
});

test("operations on a non-polygon or unknown id leave the state alone", () => {
  const boxState = { annotations: [{ id: "a1", class_id: 1, kind: "box", data: { x: 1, y: 1, w: 5, h: 5 } }], marked_empty: false, label_class_id: null };
  assert.deepEqual(moveVertex(boxState, "a1", 0, 3, 3, W, H), boxState);
  assert.deepEqual(insertVertex(boxState, "a1", 0, 3, 3, W, H), boxState);
  assert.equal(simplifyAnnotation(boxState, "a1", 5).state, boxState);
});

test("simplifyAnnotation reports before/after and returns the same state when nothing can go", () => {
  const dense = Array.from({ length: 40 }, (_, i) => [20 + i * 3, 20]).concat([[140, 80], [20, 80]]);
  const start = addPolygon(emptyState(), "a1", 1, dense);
  const { state, before, after } = simplifyAnnotation(start, "a1", 1);
  assert.equal(before, 42);
  assert.ok(after < before && after >= 3);
  assert.equal(state.annotations[0].data.points.length, after);
  const again = simplifyAnnotation(state, "a1", 1);
  assert.equal(again.state, state);
  assert.equal(again.before, again.after);
});

test("moveAnnotations moves polygons rigidly together with boxes; duplicates keep the shape", () => {
  const newId = makeIdFactory(10);
  let state = addPolygon(emptyState(), "a1", 1, square);
  state = { ...state, annotations: [...state.annotations, { id: "a2", class_id: 1, kind: "box", data: { x: 100, y: 10, w: 20, h: 20 } }] };
  const moved = moveAnnotations(state, ["a1", "a2"], 7, 3, W, H);
  assert.deepEqual(moved.annotations[0].data.points[0], [17, 13]);
  assert.deepEqual(moved.annotations[1].data, { x: 107, y: 13, w: 20, h: 20 });
  const { state: copied, ids } = duplicateAnnotations(state, ["a1"], newId, 10, W, H);
  assert.deepEqual(ids, ["a10"]);
  assert.deepEqual(copied.annotations[2].data.points[0], [20, 20]);
  assert.equal(polygonArea(copied.annotations[2].data.points), 2500);
});

test("undo/redo through 100 random steps with polygons restores the exact states", () => {
  let seed = 4242;
  const random = () => ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296);
  const newId = makeIdFactory();
  const history = createHistory(emptyState());
  const snapshots = [JSON.stringify(history.present)];
  for (let step = 0; step < 100; step++) {
    const state = history.present;
    const polygons = state.annotations.filter((a) => a.kind === "polygon");
    const pick = polygons.length ? polygons[Math.floor(random() * polygons.length)] : null;
    const roll = random();
    let next;
    if (!pick || roll < 0.25) {
      const cx = 30 + random() * 140;
      const cy = 20 + random() * 60;
      next = addPolygon(state, newId(), 1 + Math.floor(random() * 2), [[cx - 10, cy - 8], [cx + 10, cy - 8], [cx + 12, cy + 8], [cx - 12, cy + 8]]);
    } else if (roll < 0.45) {
      next = moveVertex(state, pick.id, Math.floor(random() * pick.data.points.length), random() * W, random() * H, W, H);
    } else if (roll < 0.6) {
      next = insertVertex(state, pick.id, Math.floor(random() * pick.data.points.length), random() * W, random() * H, W, H);
    } else if (roll < 0.7) {
      next = removeVertex(state, pick.id, Math.floor(random() * pick.data.points.length));
    } else if (roll < 0.8) {
      next = moveAnnotations(state, [pick.id], random() * 20 - 10, random() * 20 - 10, W, H);
    } else if (roll < 0.88) {
      next = simplifyAnnotation(state, pick.id, 3 + random() * 10).state;
    } else if (roll < 0.94) {
      next = setClass(state, [pick.id], 1 + Math.floor(random() * 2));
    } else if (roll < 0.97) {
      next = duplicateAnnotations(state, [pick.id], newId, 6, W, H).state;
    } else {
      next = deleteAnnotations(state, [pick.id]);
    }
    // Invariants that must hold after EVERY operation, independent of undo/redo:
    for (const a of next.annotations.filter((x) => x.kind === "polygon")) {
      assert.ok(a.data.points.length >= 3, `step ${step}: a polygon fell below 3 points`);
      for (const [x, y] of a.data.points) {
        assert.ok(x >= 0 && x <= W && y >= 0 && y <= H, `step ${step}: a point left the image`);
        assert.equal(x, Math.round(x * 100) / 100, `step ${step}: x not rounded to 2 decimals`);
        assert.equal(y, Math.round(y * 100) / 100, `step ${step}: y not rounded to 2 decimals`);
      }
    }
    if (history.push(next)) snapshots.push(JSON.stringify(history.present));
  }
  assert.ok(snapshots.length > 50);
  for (let i = snapshots.length - 2; i >= 0; i--) {
    history.undo();
    assert.equal(JSON.stringify(history.present), snapshots[i], `undo to step ${i}`);
  }
  for (let i = 1; i < snapshots.length; i++) {
    history.redo();
    assert.equal(JSON.stringify(history.present), snapshots[i], `redo to step ${i}`);
  }
});
