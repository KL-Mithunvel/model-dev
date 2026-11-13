import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addBox, appendFromServer, canMarkEmpty, cycle, deleteAnnotations, dropUnknownClasses,
  duplicateAnnotations, emptyState, fromServer, makeIdFactory, moveAnnotations,
  resizeAnnotationsBy, resizeAnnotationTo, setClass, setData, setLabel, setMarkedEmpty, toPayload,
} from "../../studio/web/js/editor.js";
import { createHistory } from "../../studio/web/js/history.js";

const W = 200;
const H = 100;

function deepFreeze(value) {
  if (value && typeof value === "object") {
    Object.freeze(value);
    Object.values(value).forEach(deepFreeze);
  }
  return value;
}

// ---- history ----------------------------------------------------------------------------------

test("history: push, undo, redo", () => {
  const h = createHistory({ n: 0 });
  assert.equal(h.canUndo, false);
  h.push({ n: 1 });
  h.push({ n: 2 });
  assert.deepEqual(h.undo(), { n: 1 });
  assert.deepEqual(h.undo(), { n: 0 });
  assert.equal(h.undo(), null);
  assert.deepEqual(h.redo(), { n: 1 });
  h.push({ n: 9 }); // a new edit discards the redo branch
  assert.equal(h.canRedo, false);
  assert.equal(h.redo(), null);
});

test("history: identical states are not recorded", () => {
  const h = createHistory({ n: 0 });
  assert.equal(h.push({ n: 0 }), false);
  assert.equal(h.undoDepth, 0);
});

test("history: limit drops the oldest steps", () => {
  const h = createHistory({ n: 0 }, { limit: 3 });
  for (let i = 1; i <= 10; i++) h.push({ n: i });
  assert.equal(h.undoDepth, 3);
  h.undo(); h.undo(); h.undo();
  assert.deepEqual(h.present, { n: 7 });
});

test("history: pushes with the same key inside the window share one undo step", () => {
  const h = createHistory({ x: 0 }, { coalesceMs: 600 });
  h.push({ x: 1 }, { key: "nudge", now: 1000 });
  h.push({ x: 2 }, { key: "nudge", now: 1200 });
  h.push({ x: 3 }, { key: "nudge", now: 1500 });
  assert.equal(h.undoDepth, 1);
  assert.deepEqual(h.undo(), { x: 0 });
  h.redo();
  h.push({ x: 4 }, { key: "nudge", now: 9000 }); // too late: a new step
  assert.equal(h.undoDepth, 2);
  h.push({ x: 5 }, { key: "other", now: 9100 }); // different key: a new step
  assert.equal(h.undoDepth, 3);
});

test("history: stored states are frozen so in-place edits fail loudly", () => {
  const h = createHistory({ list: [1] });
  h.push({ list: [1, 2] });
  assert.throws(() => h.present.list.push(3), TypeError);
  assert.throws(() => { h.present.list = []; }, TypeError);
});

test("history: reset forgets everything", () => {
  const h = createHistory({ n: 0 });
  h.push({ n: 1 });
  h.reset({ n: 5 });
  assert.equal(h.canUndo, false);
  assert.deepEqual(h.present, { n: 5 });
});

// ---- editor -----------------------------------------------------------------------------------

const box = (x, y, w, h) => ({ x, y, w, h });

test("editor operations return new states and never touch their input", () => {
  const newId = makeIdFactory();
  let state = deepFreeze(emptyState());
  state = deepFreeze(addBox(state, newId(), 1, box(10, 10, 50, 30)));
  state = deepFreeze(addBox(state, newId(), 2, box(100, 20, 40, 40)));
  state = deepFreeze(moveAnnotations(state, ["a1"], 5, 5, W, H));
  state = deepFreeze(setClass(state, ["a1"], 2));
  state = deepFreeze(resizeAnnotationTo(state, "a1", "se", 120, 90, W, H, 1));
  state = deepFreeze(resizeAnnotationsBy(state, ["a2"], 5, 5, W, H, 1));
  state = deepFreeze(duplicateAnnotations(state, ["a1"], newId, 10, W, H).state);
  state = deepFreeze(deleteAnnotations(state, ["a2"]));
  assert.equal(state.annotations.length, 2); // reaching here means nothing mutated a frozen input
});

test("adding an annotation clears 'no objects'; marking empty needs an empty image", () => {
  let state = setMarkedEmpty(emptyState(), true);
  assert.equal(state.marked_empty, true);
  state = addBox(state, "a1", 1, box(1, 1, 5, 5));
  assert.equal(state.marked_empty, false);
  assert.equal(canMarkEmpty(state), false);
  assert.equal(setMarkedEmpty(state, true), state); // refused: unchanged
  assert.equal(setMarkedEmpty(state, false).marked_empty, false);
});

test("boxes are rounded to two decimals and kept inside the image", () => {
  const state = addBox(emptyState(), "a1", 1, box(10.123456, 20.987654, 30.5555, 40.1111));
  assert.deepEqual(state.annotations[0].data, { x: 10.12, y: 20.99, w: 30.56, h: 40.11 });
  const moved = moveAnnotations(state, ["a1"], 9999, 9999, W, H);
  const d = moved.annotations[0].data;
  assert.ok(d.x + d.w <= W && d.y + d.h <= H);
});

test("duplicate offsets copies, gives new ids, and clamps at the edge", () => {
  const newId = makeIdFactory(10);
  const start = addBox(emptyState(), "a1", 3, box(150, 60, 50, 40));
  const { state, ids } = duplicateAnnotations(start, ["a1"], newId, 25, W, H);
  assert.deepEqual(ids, ["a10"]);
  assert.deepEqual(state.annotations[1].data, { x: 150, y: 60, w: 50, h: 40 }); // already at the corner
  assert.equal(state.annotations[1].class_id, 3);
  assert.equal(state.annotations.length, 2);
});

test("setData replaces one annotation's data; setLabel sets the image label", () => {
  const start = addBox(emptyState(), "a1", 1, box(1, 1, 9, 9));
  const changed = setData(start, "a1", box(5, 5, 20, 20));
  assert.deepEqual(changed.annotations[0].data, box(5, 5, 20, 20));
  assert.equal(setLabel(changed, 4).label_class_id, 4);
  assert.equal(setLabel(changed, null).label_class_id, null);
});

test("cycle moves through annotations and returns null past either end", () => {
  let state = emptyState();
  assert.equal(cycle(state, null, 1), null);
  state = addBox(addBox(addBox(state, "a1", 1, box(0, 0, 5, 5)), "a2", 1, box(6, 0, 5, 5)), "a3", 1, box(12, 0, 5, 5));
  assert.equal(cycle(state, null, 1), "a1");
  assert.equal(cycle(state, null, -1), "a3");
  assert.equal(cycle(state, "a1", 1), "a2");
  assert.equal(cycle(state, "a3", 1), null);
  assert.equal(cycle(state, "a1", -1), null);
});

test("server round trip keeps data and assigns client ids", () => {
  const response = {
    marked_empty: false, label_class_id: 7,
    annotations: [{ class_id: 1, kind: "box", data: box(1, 2, 3, 4) }],
  };
  const state = fromServer(response, makeIdFactory());
  assert.equal(state.annotations[0].id, "a1");
  assert.deepEqual(toPayload(state), {
    annotations: [{ class_id: 1, kind: "box", data: box(1, 2, 3, 4) }],
    marked_empty: false, label_class_id: 7,
  });
});

test("appendFromServer copies only annotations of known classes", () => {
  const response = {
    annotations: [
      { class_id: 1, kind: "box", data: box(1, 1, 5, 5) },
      { class_id: 99, kind: "box", data: box(9, 9, 5, 5) },
    ],
  };
  const { state, ids, skipped } = appendFromServer(setMarkedEmpty(emptyState(), true), response, makeIdFactory(), new Set([1]), W, H);
  assert.equal(state.annotations.length, 1);
  assert.equal(ids.length, 1);
  assert.equal(skipped, 0); // the unknown-class one is not "skipped for size"
  assert.equal(state.marked_empty, false);
});

test("appendFromServer skips shapes that do not fit a smaller image (and says how many)", () => {
  const response = {
    annotations: [
      { class_id: 1, kind: "box", data: box(10, 10, 50, 30) }, // fits 200 x 100
      { class_id: 1, kind: "box", data: box(150, 60, 100, 80) }, // sticks out of 200 x 100
      { class_id: 1, kind: "polygon", data: { points: [[10, 10], [60, 10], [60, 60]] } }, // fits
      { class_id: 1, kind: "polygon", data: { points: [[10, 10], [600, 10], [60, 60]] } }, // does not
    ],
  };
  const { state, skipped } = appendFromServer(emptyState(), response, makeIdFactory(), new Set([1]), W, H);
  assert.equal(skipped, 2);
  assert.deepEqual(state.annotations.map((a) => a.kind), ["box", "polygon"]);
  assert.equal(appendFromServer(emptyState(), response, makeIdFactory(), new Set([1]), 5000, 5000).skipped, 0);
});

test("dropUnknownClasses removes orphans and a dangling label", () => {
  let state = addBox(addBox(emptyState(), "a1", 1, box(0, 0, 5, 5)), "a2", 2, box(6, 0, 5, 5));
  state = setLabel(state, 2);
  const cleaned = dropUnknownClasses(state, new Set([1]));
  assert.deepEqual(cleaned.annotations.map((a) => a.id), ["a1"]);
  assert.equal(cleaned.label_class_id, null);
});

// ---- the plan's success criterion --------------------------------------------------------------

test("undo through 100 random steps restores the exact state, redo restores the exact end", () => {
  // Small deterministic generator so the test is repeatable.
  let seed = 12345;
  const random = () => ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296);
  const newId = makeIdFactory();
  const history = createHistory(emptyState(), { limit: 500 });
  const snapshots = [JSON.stringify(history.present)];

  for (let step = 0; step < 100; step++) {
    const state = history.present;
    const ids = state.annotations.map((a) => a.id);
    const pick = ids.length ? ids[Math.floor(random() * ids.length)] : null;
    const roll = random();
    let next;
    if (!pick || roll < 0.3) {
      const x = Math.floor(random() * 150);
      const y = Math.floor(random() * 60);
      next = addBox(state, newId(), 1 + Math.floor(random() * 3), box(x, y, 5 + random() * 40, 5 + random() * 30));
    } else if (roll < 0.5) {
      next = moveAnnotations(state, [pick], random() * 20 - 10, random() * 20 - 10, W, H);
    } else if (roll < 0.65) {
      next = resizeAnnotationTo(state, pick, "se", random() * W, random() * H, W, H, 1);
    } else if (roll < 0.75) {
      next = setClass(state, [pick], 1 + Math.floor(random() * 3));
    } else if (roll < 0.85) {
      next = duplicateAnnotations(state, [pick], newId, 8, W, H).state;
    } else if (roll < 0.95) {
      next = deleteAnnotations(state, [pick]);
    } else {
      next = setLabel(state, Math.floor(random() * 3));
    }
    if (history.push(next)) snapshots.push(JSON.stringify(history.present));
  }
  assert.ok(snapshots.length > 60, "the random walk should produce many distinct steps");

  for (let i = snapshots.length - 2; i >= 0; i--) {
    history.undo();
    assert.equal(JSON.stringify(history.present), snapshots[i], `undo to step ${i}`);
  }
  assert.equal(history.undo(), null);
  for (let i = 1; i < snapshots.length; i++) {
    history.redo();
    assert.equal(JSON.stringify(history.present), snapshots[i], `redo to step ${i}`);
  }
});

test("a keypoint set only takes a class with the same number of points", async () => {
  const { canTakeClass, setClass } = await import("../../studio/web/js/editor.js");
  const set = { id: "k", class_id: 1, kind: "keypoints", data: { points: [[1, 1, 2], [2, 2, 2], [3, 3, 2]] } };
  const box = { id: "b", class_id: 1, kind: "box", data: { x: 1, y: 1, w: 5, h: 5 } };
  const state = { annotations: [set, box], marked_empty: false, label_class_id: null };
  assert.equal(canTakeClass(set, 3), true);
  assert.equal(canTakeClass(set, 5), false);
  assert.equal(canTakeClass(set, null), false);
  assert.equal(canTakeClass(box, null), true);
  const changed = setClass(state, ["k", "b"], 2, 5);
  assert.equal(changed.annotations[0].class_id, 1); // kept
  assert.equal(changed.annotations[1].class_id, 2); // box moved
  assert.equal(setClass(state, ["k"], 2, 3).annotations[0].class_id, 2);
});
