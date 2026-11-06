// Undo/redo over immutable snapshots (no DOM). A state is any JSON-like value; it is deep-frozen
// when stored, so code that tries to edit a past state in place fails loudly instead of
// silently corrupting history.

function deepFreeze(value) {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) deepFreeze(child);
  }
  return value;
}

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

export function createHistory(initial, { limit = 500, coalesceMs = 600 } = {}) {
  let present = deepFreeze(structuredClone(initial));
  let past = [];
  let future = [];
  let lastKey = null;
  let lastTime = 0;

  return {
    get present() { return present; },
    get canUndo() { return past.length > 0; },
    get canRedo() { return future.length > 0; },
    get undoDepth() { return past.length; },

    /**
     * Record a new state. Identical states are ignored. Pushes with the same `key` within
     * `coalesceMs` of each other (for example repeated arrow-key nudges) share one undo step.
     * Returns true if the state changed.
     */
    push(next, { key = null, now = Date.now() } = {}) {
      if (same(next, present)) return false;
      const merge = key !== null && key === lastKey && now - lastTime < coalesceMs && past.length > 0;
      if (!merge) {
        past.push(present);
        if (past.length > limit) past.shift();
      }
      present = deepFreeze(structuredClone(next));
      future = [];
      lastKey = key;
      lastTime = now;
      return true;
    },

    undo() {
      if (!past.length) return null;
      future.push(present);
      present = past.pop();
      lastKey = null;
      return present;
    },

    redo() {
      if (!future.length) return null;
      past.push(present);
      present = future.pop();
      lastKey = null;
      return present;
    },

    /** Forget all history and start from `state` (for example after loading another image). */
    reset(state) {
      present = deepFreeze(structuredClone(state));
      past = [];
      future = [];
      lastKey = null;
    },
  };
}
