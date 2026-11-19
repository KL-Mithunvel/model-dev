import assert from "node:assert/strict";
import test from "node:test";

import { emptyState } from "../../studio/web/js/editor.js";
import {
  addAnnotations, classFor, matchClassId, percent, shown, toAnnotations, withIds,
} from "../../studio/web/js/suggest.js";

const classes = [{ id: 1, name: "Pallet" }, { id: 2, name: "forklift" }];
const box = (score, label = null) => ({ id: `s${score}`, kind: "box", data: { x: 1, y: 2, w: 3, h: 4 }, score, label });

test("shown filters by score (inclusive) and sorts best first", () => {
  const list = [box(0.3), box(0.9), box(0.5)];
  assert.deepEqual(shown(list, 0.5).map((s) => s.score), [0.9, 0.5]);
  assert.deepEqual(shown(list, 1).length, 0);
  assert.equal(shown(list, 0).length, 3);
});

test("class matching ignores case and spaces", () => {
  assert.equal(matchClassId("  PALLET ", classes), 1);
  assert.equal(matchClassId("Forklift", classes), 2);
  assert.equal(matchClassId("crate", classes), null);
  assert.equal(matchClassId(null, classes), null);
  assert.equal(matchClassId("", classes), null);
});

test("a suggestion falls back to the given class only when its label matches nothing", () => {
  assert.equal(classFor(box(0.9, "pallet"), classes, 2), 1);
  assert.equal(classFor(box(0.9, "crate"), classes, 2), 2);
  assert.equal(classFor(box(0.9, "crate"), classes, null), null);
});

test("toAnnotations assigns new ids, copies data, and counts suggestions without a class", () => {
  let n = 0;
  const newId = () => `a${++n}`;
  const source = box(0.9, "crate");
  const { items, skipped } = toAnnotations([box(0.9, "pallet"), source], { classes, fallbackClassId: null, newId });
  assert.equal(skipped, 1);
  assert.deepEqual(items.map((i) => [i.id, i.class_id, i.kind]), [["a1", 1, "box"]]);
  items[0].data.x = 99;
  assert.equal(source.data.x, 1, "the suggestion's own data is never shared with the annotation");
});

test("addAnnotations appends, clears 'no objects' and leaves the input state alone", () => {
  const start = { ...emptyState(), marked_empty: true };
  const next = addAnnotations(start, [{ id: "a1", class_id: 1, kind: "box", data: { x: 1, y: 1, w: 2, h: 2 } }]);
  assert.equal(next.annotations.length, 1);
  assert.equal(next.marked_empty, false);
  assert.equal(start.annotations.length, 0);
  assert.equal(start.marked_empty, true);
});

test("withIds and percent", () => {
  let n = 0;
  assert.deepEqual(withIds([{ score: 0.5 }, { score: 0.6 }], () => `s${++n}`).map((s) => s.id), ["s1", "s2"]);
  assert.equal(percent(0.873), "87%");
  assert.equal(percent(1), "100%");
});
