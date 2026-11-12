// Pure editing operations on the annotator state (no DOM). Every function returns a NEW state and
// never changes its input.
//
// state = {
//   annotations: [{ id, class_id, kind, data }],   // id is a client-side string like "a7"
//   marked_empty: boolean,                         // explicit "no objects"
//   label_class_id: number | null,                 // single-label classification
// }

import {
  NOT_LABELLED, clamp, clampPoint, movePolygon, moveBox, moveKeypoints, resizeBoxBy, resizeBoxTo,
  roundBox, roundKeypoints, roundPoints, simplifyPolygon,
} from "./geometry.js";

export const emptyState = () => ({ annotations: [], marked_empty: false, label_class_id: null });

/** Hands out ids that are unique within one editing session. */
export function makeIdFactory(start = 1) {
  let counter = start;
  return () => `a${counter++}`;
}

/** Build editor state from the server's response, giving every annotation a client id. */
export function fromServer(response, newId) {
  return {
    annotations: response.annotations.map((item) => ({
      id: newId(),
      class_id: item.class_id,
      kind: item.kind,
      data: structuredClone(item.data),
    })),
    marked_empty: Boolean(response.marked_empty),
    label_class_id: response.label_class_id ?? null,
  };
}

/** What the server's PUT expects (without `rev`). */
export function toPayload(state) {
  return {
    annotations: state.annotations.map(({ class_id, kind, data }) => ({ class_id, kind, data })),
    marked_empty: state.marked_empty,
    label_class_id: state.label_class_id,
  };
}

const withAnnotations = (state, annotations, extra = {}) => ({ ...state, annotations, ...extra });
const isTarget = (ids) => {
  const wanted = new Set(ids);
  return (annotation) => wanted.has(annotation.id);
};

/** Adding an annotation clears an earlier "no objects" mark: the two contradict each other. */
export function addAnnotation(state, annotation) {
  return withAnnotations(state, [...state.annotations, annotation], { marked_empty: false });
}

export function addBox(state, id, classId, box) {
  return addAnnotation(state, { id, class_id: classId, kind: "box", data: roundBox(box) });
}

/** Replace the data of one annotation. */
export function setData(state, id, data) {
  return withAnnotations(
    state,
    state.annotations.map((a) => (a.id === id ? { ...a, data } : a)),
  );
}

export function deleteAnnotations(state, ids) {
  const target = isTarget(ids);
  return withAnnotations(state, state.annotations.filter((a) => !target(a)));
}

export function setClass(state, ids, classId) {
  const target = isTarget(ids);
  return withAnnotations(
    state,
    state.annotations.map((a) => (target(a) ? { ...a, class_id: classId } : a)),
  );
}

/** Where a shape goes when translated by (dx, dy): boxes and polygons stop at the image edges. */
function translated(annotation, dx, dy, width, height) {
  if (annotation.kind === "box") return roundBox(moveBox(annotation.data, dx, dy, width, height));
  if (annotation.kind === "polygon") {
    return { points: roundPoints(movePolygon(annotation.data.points, dx, dy, width, height)) };
  }
  if (annotation.kind === "keypoints") {
    return { points: roundKeypoints(moveKeypoints(annotation.data.points, dx, dy, width, height)) };
  }
  return annotation.data;
}

/** Move boxes, polygons and keypoint sets by (dx, dy), clamped to the image. */
export function moveAnnotations(state, ids, dx, dy, width, height) {
  const target = isTarget(ids);
  return withAnnotations(
    state,
    state.annotations.map((a) => (target(a) ? { ...a, data: translated(a, dx, dy, width, height) } : a)),
  );
}

export function resizeAnnotationTo(state, id, handle, px, py, width, height, minSize) {
  return withAnnotations(
    state,
    state.annotations.map((a) =>
      a.id === id && a.kind === "box"
        ? { ...a, data: roundBox(resizeBoxTo(a.data, handle, px, py, width, height, minSize)) }
        : a,
    ),
  );
}

export function resizeAnnotationsBy(state, ids, dw, dh, width, height, minSize) {
  const target = isTarget(ids);
  return withAnnotations(
    state,
    state.annotations.map((a) =>
      target(a) && a.kind === "box"
        ? { ...a, data: roundBox(resizeBoxBy(a.data, dw, dh, width, height, minSize)) }
        : a,
    ),
  );
}

/**
 * Copy annotations, shifted by `offset` pixels (clamped), and append the copies.
 * Returns { state, ids } where ids are the new annotations' ids.
 */
export function duplicateAnnotations(state, ids, newId, offset, width, height) {
  const target = isTarget(ids);
  const copies = state.annotations.filter(target).map((a) => ({
    ...structuredClone(a),
    id: newId(),
    data: translated(a, offset, offset, width, height),
  }));
  return {
    state: withAnnotations(state, [...state.annotations, ...copies], { marked_empty: false }),
    ids: copies.map((c) => c.id),
  };
}

/** Does this annotation lie entirely inside a width x height image? */
export function fitsImage(item, width, height) {
  const inside = (x, y) => x >= 0 && y >= 0 && x <= width && y <= height;
  if (item.kind === "box") return inside(item.data.x, item.data.y) && inside(item.data.x + item.data.w, item.data.y + item.data.h);
  return item.data.points.every(([x, y]) => inside(x, y));
}

/**
 * Copy another image's annotations onto this one ("repeat previous image").
 * Only annotations of known classes that FIT this image are copied (the other image may have a
 * different size, and scaling would be a guess). Returns { state, ids, skipped }.
 */
export function appendFromServer(state, response, newId, validClassIds, width, height) {
  const usable = response.annotations.filter((item) => validClassIds.has(item.class_id));
  const fitting = usable.filter((item) => fitsImage(item, width, height));
  const skipped = usable.length - fitting.length;
  const incoming = fitting
    .map((item) => ({
      id: newId(),
      class_id: item.class_id,
      kind: item.kind,
      data: structuredClone(item.data),
    }));
  return {
    state: withAnnotations(state, [...state.annotations, ...incoming], {
      marked_empty: incoming.length ? false : state.marked_empty,
    }),
    ids: incoming.map((a) => a.id),
    skipped,
  };
}

/** "No objects" can only be set on an image without annotations. */
export const canMarkEmpty = (state) => state.annotations.length === 0;

export function setMarkedEmpty(state, value) {
  if (value && !canMarkEmpty(state)) return state;
  return { ...state, marked_empty: Boolean(value) };
}

export const setLabel = (state, classId) => ({ ...state, label_class_id: classId });

/** Next/previous annotation id for Tab cycling. Returns null when the end is passed. */
export function cycle(state, currentId, direction) {
  const ids = state.annotations.map((a) => a.id);
  if (!ids.length) return null;
  if (currentId === null) return direction > 0 ? ids[0] : ids[ids.length - 1];
  const next = ids.indexOf(currentId) + direction;
  return next < 0 || next >= ids.length ? null : ids[next];
}

/** Drop annotations of classes that no longer exist and clear a label that points to one. */
export function dropUnknownClasses(state, validClassIds) {
  return {
    ...state,
    annotations: state.annotations.filter((a) => validClassIds.has(a.class_id)),
    label_class_id: validClassIds.has(state.label_class_id) ? state.label_class_id : null,
  };
}

// ---- polygons -------------------------------------------------------------------------------

export function addPolygon(state, id, classId, points) {
  return addAnnotation(state, { id, class_id: classId, kind: "polygon", data: { points: roundPoints(points) } });
}

const mapPolygon = (state, id, change) =>
  withAnnotations(
    state,
    state.annotations.map((a) => (a.id === id && a.kind === "polygon" ? { ...a, data: { points: roundPoints(change(a.data.points)) } } : a)),
  );

/** Move one vertex to (x, y), kept inside the image. */
export function moveVertex(state, id, index, x, y, width, height) {
  return mapPolygon(state, id, (points) =>
    points.map((point, i) => (i === index ? clampPoint(x, y, width, height) : point)),
  );
}

/** Insert a new vertex after vertex `afterIndex` (between it and the next one). */
export function insertVertex(state, id, afterIndex, x, y, width, height) {
  return mapPolygon(state, id, (points) => [
    ...points.slice(0, afterIndex + 1),
    clampPoint(x, y, width, height),
    ...points.slice(afterIndex + 1),
  ]);
}

/** Remove a vertex. A polygon needs 3 points: with 3 left the state is returned unchanged. */
export function removeVertex(state, id, index) {
  const polygon = state.annotations.find((a) => a.id === id && a.kind === "polygon");
  if (!polygon || polygon.data.points.length <= 3) return state;
  return mapPolygon(state, id, (points) => points.filter((_, i) => i !== index));
}

/**
 * Drop points closer than `epsilon` pixels to the simplified outline.
 * Returns { state, before, after } (the same state object when nothing could be removed).
 */
export function simplifyAnnotation(state, id, epsilon) {
  const polygon = state.annotations.find((a) => a.id === id && a.kind === "polygon");
  if (!polygon) return { state, before: 0, after: 0 };
  const before = polygon.data.points.length;
  const reduced = simplifyPolygon(polygon.data.points, epsilon);
  if (reduced.length >= before) return { state, before, after: before };
  return { state: mapPolygon(state, id, () => reduced), before, after: reduced.length };
}

// ---- keypoints ------------------------------------------------------------------------------

export function addKeypoints(state, id, classId, points) {
  return addAnnotation(state, { id, class_id: classId, kind: "keypoints", data: { points: roundKeypoints(points) } });
}

const mapKeypoints = (state, id, change) =>
  withAnnotations(
    state,
    state.annotations.map((a) => (a.id === id && a.kind === "keypoints" ? { ...a, data: { points: roundKeypoints(change(a.data.points)) } } : a)),
  );

/**
 * Put point `index` at (x, y) with visibility `v` (1 or 2), inside the image. Used to place a
 * point for the first time and to drag it; a point that was not labelled becomes labelled.
 */
export function placeKeypoint(state, id, index, x, y, v, width, height) {
  return mapKeypoints(state, id, (points) =>
    points.map((point, i) => (i === index ? [clamp(x, 0, width), clamp(y, 0, height), v] : point)),
  );
}

/**
 * Change one point's visibility. Making it "not labelled" is refused (state returned unchanged)
 * when it is the last labelled point, because the server needs at least one. A point that was not
 * labelled and becomes labelled needs a place: `fallback` = [x, y].
 */
export function setKeypointVisibility(state, id, index, v, fallback = [0, 0]) {
  const item = state.annotations.find((a) => a.id === id && a.kind === "keypoints");
  if (!item || !item.data.points[index]) return state;
  const points = item.data.points;
  if (v === NOT_LABELLED && points.filter((p, i) => i !== index && p[2] > NOT_LABELLED).length === 0) {
    return state;
  }
  return mapKeypoints(state, id, (all) =>
    all.map((point, i) => {
      if (i !== index) return point;
      if (v === NOT_LABELLED) return [0, 0, 0];
      return point[2] === NOT_LABELLED ? [fallback[0], fallback[1], v] : [point[0], point[1], v];
    }),
  );
}
