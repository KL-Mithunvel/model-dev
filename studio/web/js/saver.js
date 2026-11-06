// Autosave for one image (no DOM). Guarantees:
//   * every edit is written to a local draft SYNCHRONOUSLY, so killing the tab loses nothing;
//   * saves are debounced and never overlap (one request in flight at a time);
//   * edits made while a save is in flight are saved right after it;
//   * a failed save is retried with back-off and never discards the pending edit;
//   * a revision conflict stops saving and is reported, keeping the draft.

const DEFAULT_RETRY_MS = [2000, 5000, 15000];

export const draftKey = (imageId) => `studio.draft.${imageId}`;

export function readDraft(storage, imageId) {
  try {
    const raw = storage.getItem(draftKey(imageId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function clearDraft(storage, imageId) {
  try {
    storage.removeItem(draftKey(imageId));
  } catch {
    /* storage unavailable: nothing to clear */
  }
}

/**
 * send(payload, rev) must resolve to { ok: true, rev } or { conflict: true, currentRev }, or reject
 * for network/server errors. `timers` and `storage` are injectable for tests.
 */
export function createSaver({
  imageId,
  rev,
  send,
  debounceMs = 400,
  retryMs = DEFAULT_RETRY_MS,
  storage = null,
  onStatus = () => {},
  timers = { set: (fn, ms) => setTimeout(fn, ms), clear: (id) => clearTimeout(id) },
}) {
  let currentRev = rev;
  let pending = null; // the newest payload that has not been saved yet
  let inflight = null; // promise of the running save
  let timer = null;
  let failures = 0;
  let status = "saved";
  let stopped = false; // true after a conflict or dispose

  const setStatus = (next, detail) => {
    status = next;
    onStatus(next, detail);
  };

  const writeDraft = (payload) => {
    if (!storage) return;
    try {
      storage.setItem(draftKey(imageId), JSON.stringify({ baseRev: currentRev, payload, at: Date.now() }));
    } catch {
      /* quota or private mode: autosave to the server still works */
    }
  };

  const schedule = (ms) => {
    if (timer !== null) timers.clear(timer);
    timer = timers.set(() => {
      timer = null;
      void run();
    }, ms);
  };

  async function run() {
    if (inflight || pending === null || stopped) return inflight;
    const payload = pending;
    pending = null;
    setStatus("saving");
    inflight = (async () => {
      try {
        const result = await send(payload, currentRev);
        if (result.conflict) {
          stopped = true;
          pending = payload;
          setStatus("conflict", { currentRev: result.currentRev });
          return;
        }
        currentRev = result.rev;
        failures = 0;
        if (pending === null) {
          if (storage) clearDraft(storage, imageId);
          setStatus("saved");
        } else {
          writeDraft(pending); // newer edits arrived while saving; draft now has the new base rev
          setStatus("dirty");
          schedule(0);
        }
      } catch (error) {
        if (pending === null) pending = payload; // keep the edit; a newer one (if any) supersedes it
        setStatus("error", { error });
        const delay = retryMs[Math.min(failures, retryMs.length - 1)];
        failures += 1;
        if (!stopped) schedule(delay);
      } finally {
        inflight = null;
      }
    })();
    return inflight;
  }

  return {
    get status() { return status; },
    get rev() { return currentRev; },
    get hasUnsavedChanges() { return pending !== null || inflight !== null; },

    /** Call after every edit. */
    edit(payload) {
      if (stopped) return;
      pending = payload;
      writeDraft(payload);
      setStatus("dirty");
      schedule(debounceMs);
    },

    /** Save now and wait until nothing is pending (or saving is stopped by an error). */
    async flush() {
      if (timer !== null) {
        timers.clear(timer);
        timer = null;
      }
      for (let guard = 0; guard < 20; guard++) {
        if (inflight) await inflight;
        if (pending === null || stopped || status === "error") break;
        await run();
      }
    },

    /** The payload that is not on the server yet, for a last-chance send on page hide. */
    takePendingForBeacon() { return pending; },
    get currentRev() { return currentRev; },

    /** After the caller reloaded from the server (resolving a conflict or restoring a draft). */
    reset(newRev) {
      currentRev = newRev;
      pending = null;
      stopped = false;
      failures = 0;
      if (timer !== null) {
        timers.clear(timer);
        timer = null;
      }
      if (storage) clearDraft(storage, imageId);
      setStatus("saved");
    },

    dispose() {
      stopped = true;
      if (timer !== null) timers.clear(timer);
    },
  };
}
