// Autosave for one image (no DOM). Guarantees:
//   * every edit is written to a local draft SYNCHRONOUSLY, so killing the tab loses nothing;
//   * saves are debounced and never overlap (one request in flight at a time);
//   * edits made while a save is in flight are saved right after it;
//   * a failed save is retried with back-off and never discards the pending edit;
//   * a revision conflict stops saving and is reported, keeping the draft;
//   * the server refusing the content (a 4xx other than a conflict) is reported with its reason
//     and is NOT retried (retrying cannot help), but the next edit tries again;
//   * flushNow() sends at once through the same single-flight path, so leaving the page can never
//     produce a second request with a stale revision.

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
 * send(payload, rev, options) must resolve to { ok: true, rev }, { conflict: true, currentRev } or
 * { rejected: true, message }, or reject for network/server errors (which are retried). `timers` and `storage` are injectable for tests.
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
  let stopped = false; // true after a conflict: no more sends until reset()
  let disposed = false; // true after dispose(): nothing is sent or scheduled any more
  let rejected = false; // the server refused the last payload; a new edit tries again

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

  async function run(options = {}) {
    if (inflight || pending === null || stopped || disposed || rejected) return inflight;
    const payload = pending;
    pending = null;
    setStatus("saving");
    inflight = (async () => {
      try {
        const result = await send(payload, currentRev, options);
        if (result.rejected) {
          rejected = true;
          pending = pending ?? payload; // keep the edit; do not retry what the server refuses
          setStatus("rejected", { message: result.message });
          return;
        }
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
        if (!stopped && !disposed) schedule(delay);
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
      if (disposed) return;
      pending = payload;
      writeDraft(payload); // always, even after a conflict: the draft is the safety net
      if (stopped) return; // conflict: wait for the user's choice before sending anything
      rejected = false;
      setStatus("dirty");
      schedule(debounceMs);
    },

    /** Send the pending edit right now (page hidden or closing). `options` go to send(). */
    flushNow(options = {}) {
      if (timer !== null) {
        timers.clear(timer);
        timer = null;
      }
      return run(options);
    },

    /** Save now and wait until nothing is pending (or saving is stopped by an error). */
    async flush() {
      if (timer !== null) {
        timers.clear(timer);
        timer = null;
      }
      for (let guard = 0; guard < 20; guard++) {
        if (inflight) await inflight;
        if (pending === null || stopped || rejected || status === "error") break;
        await run();
      }
    },


    /** After the caller reloaded from the server (resolving a conflict or restoring a draft). */
    reset(newRev) {
      currentRev = newRev;
      pending = null;
      stopped = false;
      rejected = false;
      failures = 0;
      if (timer !== null) {
        timers.clear(timer);
        timer = null;
      }
      if (storage) clearDraft(storage, imageId);
      setStatus("saved");
    },

    dispose() {
      disposed = true;
      if (timer !== null) timers.clear(timer);
    },
  };
}
