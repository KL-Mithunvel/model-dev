// Pure editing operations on the annotator state (no DOM). Every function returns a NEW state and
// never changes its input.
//
// state = {
//   annotations: [{ id, class_id, kind, data }],   // id is a client-side string like "a7"
//   marked_empty: boolean,                         // explicit "no objects"
//   label_class_id: number | null,                 // single-label classification
// }

import { moveBox, resizeBoxBy, resizeBoxTo, roundBox } from "./geometry.js";

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

/** Move boxes by (dx, dy), clamped to the image. */
export function moveAnnotations(state, ids, dx, dy, width, height) {
  const target = isTarget(ids);
  return withAnnotations(
    state,
    state.annotations.map((a) =>
      target(a) && a.kind === "box"
        ? { ...a, data: roundBox(moveBox(a.data, dx, dy, width, height)) }
        : a,
    ),
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
    data: a.kind === "box" ? roundBox(moveBox(a.data, offset, offset, width, height)) : structuredClone(a.data),
  }));
  return {
    state: withAnnotations(state, [...state.annotations, ...copies], { marked_empty: false }),
    ids: copies.map((c) => c.id),
  };
}

/** Copy another image's annotations onto this one ("repeat previous image"). */
export function appendFromServer(state, response, newId, validClassIds) {
  const incoming = response.annotations
    .filter((item) => validClassIds.has(item.class_id))
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
