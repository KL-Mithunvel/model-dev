import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addKeypoints, deleteAnnotations, duplicateAnnotations, emptyState, makeIdFactory,
  moveAnnotations, placeKeypoint, setKeypointVisibility,
} from "../../studio/web/js/editor.js";
import {
  defaultKeypoints, keypointsBounds, moveKeypoints, nearestKeypoint, nextUnplaced, nextVisibility,
  roundKeypoints,
} from "../../studio/web/js/geometry.js";
import { createHistory } from "../../studio/web/js/history.js";

const W = 200;
const H = 100;
const pose = [[10, 10, 2], [50, 20, 1], [0, 0, 0], [90, 60, 2]];

function deepFreeze(value) {
  if (value && typeof value === "object") {
    Object.freeze(value);
    Object.values(value).forEach(deepFreeze);
  }
  return value;
}

test("bounds ignore points that are not labelled", () => {
  assert.deepEqual(keypointsBounds(pose), { minX: 10, minY: 10, maxX: 90, maxY: 60, w: 80, h: 50 });
  assert.equal(keypointsBounds([[0, 0, 0], [0, 0, 0]]), null);
});

test("roundKeypoints rounds and zeroes unlabelled points", () => {
  assert.deepEqual(roundKeypoints([[1.234, 5.678, 2], [9, 9, 0]]), [[1.23, 5.68, 2], [0, 0, 0]]);
});

test("moveKeypoints moves the labelled group rigidly and stops at the edges", () => {
  assert.deepEqual(moveKeypoints(pose, 5, 5, W, H), [[15, 15, 2], [55, 25, 1], [0, 0, 0], [95, 65, 2]]);
  const left = moveKeypoints(pose, -999, 0, W, H);
  assert.equal(left[0][0], 0); // left-most labelled point reaches the edge
  assert.equal(left[3][0], 80); // and the others kept their distance
  assert.deepEqual(left[2], [0, 0, 0]); // an unlabelled point never moves
  assert.deepEqual(moveKeypoints([[0, 0, 0]], 5, 5, W, H), [[0, 0, 0]]);
});

test("nextVisibility cycles visible -> hidden -> not labelled -> visible", () => {
  assert.deepEqual([2, 1, 0].map(nextVisibility), [1, 0, 2]);
});

test("nearestKeypoint picks the closest labelled point within the radius", () => {
  assert.equal(nearestKeypoint(pose, 52, 21, 5), 1);
  assert.equal(nearestKeypoint(pose, 1, 1, 5), -1); // the unlabelled point at 0,0 is not a target
  assert.equal(nearestKeypoint(pose, 30, 40, 5), -1);
});

test("nextUnplaced finds the next point that still needs a place", () => {
  assert.equal(nextUnplaced(pose), 2);
  assert.equal(nextUnplaced(pose, 3), -1);
});

test("defaultKeypoints puts every point inside the image, all visible", () => {
  const points = defaultKeypoints(5, 100, 50, W, H, W, H);
  assert.equal(points.length, 5);
  for (const [x, y, v] of points) {
    assert.ok(x >= 0 && x <= W && y >= 0 && y <= H);
    assert.equal(v, 2);
  }
  const corner = defaultKeypoints(3, 0, 0, W, H, W, H); // centre far outside: still inside
  for (const [x, y] of corner) assert.ok(x >= 0 && y >= 0);
});

test("addKeypoints, placeKeypoint and moving never change the old state", () => {
  const ids = makeIdFactory();
  const start = deepFreeze(emptyState());
  const added = deepFreeze(addKeypoints(start, ids(), 7, pose));
  assert.equal(added.annotations[0].kind, "keypoints");
  const id = added.annotations[0].id;
  const placed = deepFreeze(placeKeypoint(added, id, 2, 120.456, 70, 2, W, H));
  assert.deepEqual(placed.annotations[0].data.points[2], [120.46, 70, 2]);
  assert.deepEqual(added.annotations[0].data.points[2], [0, 0, 0]);
  const clamped = placeKeypoint(placed, id, 2, 999, -5, 1, W, H);
  assert.deepEqual(clamped.annotations[0].data.points[2], [200, 0, 1]);
  const moved = moveAnnotations(placed, [id], 3, 3, W, H);
  assert.deepEqual(moved.annotations[0].data.points[0], [13, 13, 2]);
});

test("setKeypointVisibility keeps at least one labelled point and gives new points a place", () => {
  const id = "a1";
  const state = addKeypoints(emptyState(), id, 1, [[10, 10, 2], [0, 0, 0]]);
  assert.equal(setKeypointVisibility(state, id, 0, 0), state); // would leave none labelled
  const label = setKeypointVisibility(state, id, 1, 1, [40, 40]);
  assert.deepEqual(label.annotations[0].data.points[1], [40, 40, 1]);
  const clear = setKeypointVisibility(label, id, 0, 0);
  assert.deepEqual(clear.annotations[0].data.points[0], [0, 0, 0]);
  const hidden = setKeypointVisibility(label, id, 0, 1);
  assert.deepEqual(hidden.annotations[0].data.points[0], [10, 10, 1]); // keeps its place
});

test("duplicate and delete work for keypoint sets", () => {
  const ids = makeIdFactory(5);
  const state = addKeypoints(emptyState(), "a1", 1, pose);
  const { state: doubled, ids: copies } = duplicateAnnotations(state, ["a1"], ids, 10, W, H);
  assert.equal(doubled.annotations.length, 2);
  assert.deepEqual(doubled.annotations[1].data.points[0], [20, 20, 2]);
  assert.equal(deleteAnnotations(doubled, copies).annotations.length, 1);
});

test("a placed point is one undo step", () => {
  const history = createHistory(addKeypoints(emptyState(), "a1", 1, [[10, 10, 2], [0, 0, 0]]), { limit: 50 });
  history.push(placeKeypoint(history.present, "a1", 1, 30, 30, 2, W, H));
  history.undo();
  assert.deepEqual(history.present.annotations[0].data.points[1], [0, 0, 0]);
});
