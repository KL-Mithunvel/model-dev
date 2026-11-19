// Pure chart maths for the hardware monitor (no DOM, unit-tested in tests/js/chart.test.mjs).
// A "sample" is {t: seconds, values: {key: number}}; t is wall-clock seconds for live samples and
// seconds since the run started for stored rows. A line is split wherever data is missing.

/** Round `value` up to 1, 2, 5 or 10 times a power of ten, never below `floor`. */
export function niceMax(value, floor = 1) {
  const target = Math.max(value, floor);
  const power = 10 ** Math.floor(Math.log10(target));
  for (const step of [1, 2, 5, 10]) {
    if (step * power >= target) return step * power;
  }
  return 10 * power;
}

/** The upper end of the y axis: the known maximum if there is one, otherwise a nice number above the data. */
export function axisMax(samples, keys, knownMax, floor = 1) {
  if (knownMax) return knownMax;
  let top = 0;
  for (const sample of samples) {
    for (const key of keys) {
      const value = sample.values[key];
      if (value !== undefined && value > top) top = value;
    }
  }
  return niceMax(top * 1.1, floor);
}

/**
 * Turn samples into line segments of [x, y] pixel pairs. `endT` is the time at the right edge and
 * `windowS` the span shown. A gap longer than `gapS` between two samples starts a new segment, so
 * a paused sampler shows as a break and not as a false straight line.
 */
export function segments(samples, key, { endT, windowS, width, height, yMax, gapS }) {
  const out = [];
  let current = [];
  let previousT = null;
  for (const sample of samples) {
    const value = sample.values[key];
    if (value === undefined || sample.t < endT - windowS || sample.t > endT) continue;
    if (previousT !== null && sample.t - previousT > gapS && current.length) {
      out.push(current);
      current = [];
    }
    const x = ((sample.t - (endT - windowS)) / windowS) * width;
    const y = height - (Math.min(Math.max(value, 0), yMax) / yMax) * height;
    current.push([round(x), round(y)]);
    previousT = sample.t;
  }
  if (current.length) out.push(current);
  return out;
}

/** SVG path data for segments. A single point becomes a tiny horizontal tick so it stays visible. */
export function pathData(segmentList) {
  return segmentList
    .map((points) => {
      const [first, ...rest] = points;
      if (!rest.length) return `M${first[0]} ${first[1]}h0.01`;
      return `M${first[0]} ${first[1]}${rest.map(([x, y]) => `L${x} ${y}`).join("")}`;
    })
    .join("");
}

/** A number with its unit, using as few digits as keep it readable. */
export function formatValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const digits = Math.abs(value) >= 100 || unit === "MHz" ? 0 : 1;
  const text = value.toFixed(digits);
  return unit === "%" || unit === "°C" ? `${text} ${unit}` : unit ? `${text} ${unit}` : text;
}

/** "60 s", "5 min", "15 min" for a window in seconds. */
export function windowLabel(seconds) {
  return seconds < 120 ? `${seconds} s` : `${Math.round(seconds / 60)} min`;
}

/** The latest value of `key` in samples, or null. */
export function latestValue(samples, key) {
  for (let index = samples.length - 1; index >= 0; index -= 1) {
    const value = samples[index].values[key];
    if (value !== undefined) return value;
  }
  return null;
}

/** Minutes and seconds as "m:ss" for run lengths. */
export function formatDuration(seconds) {
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  const rest = String(whole % 60).padStart(2, "0");
  return minutes >= 60 ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

function round(number) {
  return Math.round(number * 100) / 100;
}
