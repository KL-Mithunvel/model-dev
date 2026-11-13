import assert from "node:assert/strict";
import { test } from "node:test";

import { PRESETS, parseSkeleton, skeletonToText } from "../../studio/web/js/skeleton.js";

test("text and skeleton convert both ways", () => {
  const skeleton = { names: ["head", "left-eye", "tail"], edges: [[0, 1], [0, 2]] };
  const text = skeletonToText(skeleton);
  assert.equal(text.points, "head\nleft-eye\ntail");
  assert.equal(text.connections, "head - left-eye\nhead - tail");
  assert.deepEqual(parseSkeleton(text.points, text.connections).skeleton, skeleton);
});

test("no points means no skeleton; connections alone are an error", () => {
  assert.deepEqual(parseSkeleton("  \n", ""), { skeleton: null });
  assert.match(parseSkeleton("", "a - b").error, /List the points first/);
  assert.deepEqual(skeletonToText(null), { points: "", connections: "" });
});

test("names are tidied, duplicates and long names refused", () => {
  assert.deepEqual(parseSkeleton("  head  top \n\nneck", "").skeleton.names, ["head top", "neck"]);
  assert.match(parseSkeleton("a\nA", "").error, /listed twice/);
  assert.match(parseSkeleton("x".repeat(41), "").error, /longer than 40/);
  assert.match(parseSkeleton("a\nb", "", { maxPoints: 1 }).error, /At most 1/);
});

test("connections are checked, ordered and de-duplicated", () => {
  const ok = parseSkeleton("a\nb\nc", "c - a\na - c\nb - c");
  assert.deepEqual(ok.skeleton.edges, [[0, 2], [1, 2]]);
  assert.match(parseSkeleton("a\nb", "a - z").error, /“z” is not in the list/);
  assert.match(parseSkeleton("a\nb", "a - a").error, /itself/);
  assert.match(parseSkeleton("a\nb", "a b").error, /spaced hyphen/);
  assert.match(parseSkeleton("a\nb", "a - b - c").error, /spaced hyphen/);
});

test("presets are valid: unique names, edges inside range", () => {
  for (const preset of Object.values(PRESETS)) {
    assert.equal(new Set(preset.names.map((n) => n.toLowerCase())).size, preset.names.length);
    for (const [a, b] of preset.edges) assert.ok(a !== b && a >= 0 && b < preset.names.length);
    const text = skeletonToText(preset);
    assert.deepEqual(parseSkeleton(text.points, text.connections).skeleton.names, preset.names);
  }
});

test("names that differ only by case folding are duplicates, like on the server", () => {
  assert.match(parseSkeleton("é\nÉ", "").error, /listed twice/);
  assert.match(parseSkeleton("ß\nSS", "").error, /listed twice/);
});
