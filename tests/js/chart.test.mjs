import assert from "node:assert/strict";
import test from "node:test";

import {
  axisMax, formatDuration, formatValue, latestValue, niceMax, pathData, segments, windowLabel,
} from "../../studio/web/js/chart.js";

const frame = { endT: 100, windowS: 60, width: 600, height: 100, yMax: 100, gapS: 2.5 };
const sample = (t, value) => ({ t, values: { a: value } });

test("niceMax rounds up to 1, 2, 5 or 10 times a power of ten", () => {
  assert.equal(niceMax(0.3, 1), 1);
  assert.equal(niceMax(1.1), 2);
  assert.equal(niceMax(3), 5);
  assert.equal(niceMax(5.1), 10);
  assert.equal(niceMax(47), 50);
  assert.equal(niceMax(100), 100);
  assert.equal(niceMax(101), 200);
});

test("axisMax uses the known maximum, else the data with headroom and a floor", () => {
  assert.equal(axisMax([sample(1, 5)], ["a"], 100), 100);
  assert.equal(axisMax([sample(1, 4), sample(2, 9)], ["a"], null), 10);
  assert.equal(axisMax([], ["a"], null, 5), 5);
});

test("segments place the newest sample at the right edge and the value from the bottom", () => {
  const [line] = segments([sample(40, 0), sample(100, 100)], "a", { ...frame, gapS: 100 });
  assert.deepEqual(line, [[0, 100], [600, 0]]);
});

test("segments clamp values to the axis and drop samples outside the window", () => {
  const out = segments([sample(10, 50), sample(70, 500), sample(101, 5)], "a", frame);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0], [[300, 0]]); // t=70 is inside; 500 is clamped to the top
});

test("a long gap splits the line instead of drawing across it", () => {
  const out = segments([sample(90, 10), sample(91, 10), sample(97, 10), sample(98, 10)], "a", frame);
  assert.equal(out.length, 2);
});

test("a sample that lacks the key is skipped, not drawn as zero", () => {
  const out = segments([sample(98, 10), { t: 99, values: {} }, sample(100, 10)], "a", frame);
  assert.equal(out.length, 1);
  assert.equal(out[0].length, 2);
});

test("pathData draws lines and keeps a lone point visible", () => {
  assert.equal(pathData([[[0, 1], [2, 3]]]), "M0 1L2 3");
  assert.equal(pathData([[[5, 5]]]), "M5 5h0.01");
  assert.equal(pathData([]), "");
});

test("formatValue", () => {
  assert.equal(formatValue(null, "%"), "–");
  assert.equal(formatValue(12.34, "%"), "12.3 %");
  assert.equal(formatValue(1740, "MHz"), "1740 MHz");
  assert.equal(formatValue(123.4, "W"), "123 W");
  assert.equal(formatValue(0.2, "GB"), "0.2 GB");
});

test("windowLabel and formatDuration", () => {
  assert.equal(windowLabel(60), "60 s");
  assert.equal(windowLabel(300), "5 min");
  assert.equal(formatDuration(65), "1:05");
  assert.equal(formatDuration(3725), "1:02:05");
  assert.equal(formatDuration(-3), "0:00");
});

test("latestValue finds the last sample that has the key", () => {
  assert.equal(latestValue([sample(1, 5), { t: 2, values: {} }], "a"), 5);
  assert.equal(latestValue([], "a"), null);
});
