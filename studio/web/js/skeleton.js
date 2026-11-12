// Turning a class's skeleton into editable text and back (pure, no DOM, unit-tested).
//   points:       one name per line
//   connections:  one per line, "name - name" (a spaced hyphen, so names may contain hyphens)

export const EDGE_SEPARATOR = " - ";

const clean = (text) => text.split(/\s+/).filter(Boolean).join(" ");
const same = (a, b) => a.toLowerCase() === b.toLowerCase();

/** The two text boxes for a skeleton (or empty ones). */
export function skeletonToText(skeleton) {
  if (!skeleton) return { points: "", connections: "" };
  return {
    points: skeleton.names.join("\n"),
    connections: skeleton.edges.map(([a, b]) => `${skeleton.names[a]}${EDGE_SEPARATOR}${skeleton.names[b]}`).join("\n"),
  };
}

/**
 * Read the two text boxes. Returns { skeleton } (null when there are no points at all) or
 * { error } with a message that says what to fix. The server checks everything again.
 */
export function parseSkeleton(pointsText, connectionsText, { maxPoints = 64, nameMax = 40 } = {}) {
  const names = pointsText.split("\n").map(clean).filter(Boolean);
  if (!names.length) {
    return clean(connectionsText) ? { error: "Connections need points. List the points first." } : { skeleton: null };
  }
  if (names.length > maxPoints) return { error: `At most ${maxPoints} points (you listed ${names.length}).` };
  for (const [i, name] of names.entries()) {
    if (name.length > nameMax) return { error: `Point ${i + 1} is longer than ${nameMax} characters.` };
    const first = names.findIndex((other) => same(other, name));
    if (first !== i) return { error: `“${name}” is listed twice (points ${first + 1} and ${i + 1}).` };
  }
  const edges = [];
  for (const [n, line] of connectionsText.split("\n").entries()) {
    const text = line.trim();
    if (!text) continue;
    const parts = text.split(/\s+-\s+/).map(clean);
    if (parts.length !== 2 || !parts[0] || !parts[1]) {
      return { error: `Connection ${n + 1}: write two point names with a spaced hyphen, like “head - neck”.` };
    }
    const ends = parts.map((part) => names.findIndex((name) => same(name, part)));
    const missing = ends.findIndex((index) => index < 0);
    if (missing >= 0) return { error: `Connection ${n + 1}: “${parts[missing]}” is not in the list of points.` };
    if (ends[0] === ends[1]) return { error: `Connection ${n + 1} joins a point to itself.` };
    const edge = ends[0] < ends[1] ? ends : [ends[1], ends[0]];
    if (!edges.some(([a, b]) => a === edge[0] && b === edge[1])) edges.push(edge);
  }
  return { skeleton: { names, edges } };
}

/** Ready-made skeletons to start from. */
export const PRESETS = {
  "Person (17 points, COCO)": {
    names: ["nose", "left eye", "right eye", "left ear", "right ear", "left shoulder", "right shoulder", "left elbow", "right elbow", "left wrist", "right wrist", "left hip", "right hip", "left knee", "right knee", "left ankle", "right ankle"],
    edges: [[15, 13], [13, 11], [16, 14], [14, 12], [11, 12], [5, 11], [6, 12], [5, 6], [5, 7], [6, 8], [7, 9], [8, 10], [1, 2], [0, 1], [0, 2], [1, 3], [2, 4], [3, 5], [4, 6]],
  },
  "Hand (21 points)": {
    names: ["wrist", "thumb 1", "thumb 2", "thumb 3", "thumb tip", "index 1", "index 2", "index 3", "index tip", "middle 1", "middle 2", "middle 3", "middle tip", "ring 1", "ring 2", "ring 3", "ring tip", "pinky 1", "pinky 2", "pinky 3", "pinky tip"],
    edges: [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [0, 9], [9, 10], [10, 11], [11, 12], [0, 13], [13, 14], [14, 15], [15, 16], [0, 17], [17, 18], [18, 19], [19, 20]],
  },
};
