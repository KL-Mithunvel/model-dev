// Pure logic for AI suggestions (no DOM, unit-tested in tests/js/suggest.test.mjs).
// A suggestion is {id, kind: "box"|"polygon", data, score (0..1), label: string|null}. Suggestions are
// never part of the annotation state: they only become annotations through `toAnnotations` + an
// explicit accept, and then go through the same history and save path as hand-drawn shapes.
import { addAnnotation } from "./editor.js";

/** Suggestions at or above `minScore`, best first. */
export function shown(suggestions, minScore) {
  return suggestions.filter((s) => s.score >= minScore).sort((a, b) => b.score - a.score);
}

/** The id of the project class whose name equals `label` (case-insensitive, trimmed), or null. */
export function matchClassId(label, classes) {
  if (!label) return null;
  const wanted = label.trim().toLowerCase();
  return classes.find((c) => c.name.trim().toLowerCase() === wanted)?.id ?? null;
}

/** The class a suggestion would get: its matching class, else `fallbackClassId` (may be null). */
export function classFor(suggestion, classes, fallbackClassId) {
  return matchClassId(suggestion.label, classes) ?? fallbackClassId ?? null;
}

/**
 * Turn accepted suggestions into annotations. Returns {items, skipped}: `skipped` counts suggestions
 * that got no class (no matching class and no fallback), which the caller reports.
 */
export function toAnnotations(accepted, { classes, fallbackClassId, newId }) {
  const items = [];
  let skipped = 0;
  for (const suggestion of accepted) {
    const classId = classFor(suggestion, classes, fallbackClassId);
    if (classId === null) {
      skipped += 1;
      continue;
    }
    items.push({ id: newId(), class_id: classId, kind: suggestion.kind, data: structuredClone(suggestion.data) });
  }
  return { items, skipped };
}

/** The state with `items` appended (also clears "no objects", like any added annotation). */
export function addAnnotations(state, items) {
  return items.reduce((next, item) => addAnnotation(next, item), state);
}

/** Give each raw suggestion from the server a local id so the panel can refer to it. */
export function withIds(raw, newId) {
  return raw.map((item) => ({ ...item, id: newId() }));
}

/** Percentage text for a score: 0.873 -> "87%". */
export const percent = (score) => `${Math.round(score * 100)}%`;
