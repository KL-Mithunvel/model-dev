import assert from "node:assert/strict";
import { test } from "node:test";

import { clearDraft, createSaver, draftKey, readDraft } from "../../studio/web/js/saver.js";

/** Manual clock so tests never wait for real time. */
function fakeTimers() {
  let now = 0;
  let nextId = 1;
  const queue = new Map();
  return {
    set(fn, ms) { const id = nextId++; queue.set(id, { at: now + ms, fn }); return id; },
    clear(id) { queue.delete(id); },
    async advance(ms) {
      const end = now + ms;
      for (;;) {
        const due = [...queue.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        queue.delete(due[0]);
        now = due[1].at;
        due[1].fn();
        await flushMicrotasks();
      }
      now = end;
    },
    get pending() { return queue.size; },
  };
}
const flushMicrotasks = () => new Promise((resolve) => setImmediate(resolve));

function fakeStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, v),
    removeItem: (k) => map.delete(k),
    has: (k) => map.has(k),
  };
}

const payload = (n) => ({ annotations: [{ class_id: 1, kind: "box", data: { x: n, y: 0, w: 5, h: 5 } }], marked_empty: false, label_class_id: null });

test("many quick edits become one save with the newest payload", async () => {
  const timers = fakeTimers();
  const sent = [];
  const saver = createSaver({ imageId: 1, rev: 0, debounceMs: 400, timers, send: async (p, rev) => { sent.push([p, rev]); return { ok: true, rev: rev + 1 }; } });
  for (let n = 1; n <= 10; n++) saver.edit(payload(n));
  assert.equal(sent.length, 0);
  await timers.advance(399);
  assert.equal(sent.length, 0);
  await timers.advance(2);
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], [payload(10), 0]);
  assert.equal(saver.rev, 1);
  assert.equal(saver.status, "saved");
});

test("the draft is written synchronously on every edit and removed after a successful save", async () => {
  const timers = fakeTimers();
  const storage = fakeStorage();
  const saver = createSaver({ imageId: 5, rev: 3, storage, timers, send: async (p, rev) => ({ ok: true, rev: rev + 1 }) });
  saver.edit(payload(1));
  assert.ok(storage.has(draftKey(5)), "draft exists immediately, before any timer fires");
  assert.deepEqual(readDraft(storage, 5).payload, payload(1));
  assert.equal(readDraft(storage, 5).baseRev, 3);
  await timers.advance(1000);
  assert.equal(readDraft(storage, 5), null);
});

test("edits made while a save is in flight are saved right after it", async () => {
  const timers = fakeTimers();
  const sent = [];
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const saver = createSaver({
    imageId: 1, rev: 0, timers,
    send: async (p, rev) => { sent.push([p, rev]); if (sent.length === 1) await gate; return { ok: true, rev: rev + 1 }; },
  });
  saver.edit(payload(1));
  await timers.advance(500);
  assert.equal(sent.length, 1);
  saver.edit(payload(2)); // arrives mid-save
  assert.equal(saver.hasUnsavedChanges, true);
  release();
  await flushMicrotasks();
  await timers.advance(1);
  assert.equal(sent.length, 2);
  assert.deepEqual(sent[1], [payload(2), 1]); // uses the new revision from the first save
  assert.equal(saver.status, "saved");
});

test("saves never overlap", async () => {
  const timers = fakeTimers();
  let running = 0;
  let maxRunning = 0;
  const saver = createSaver({
    imageId: 1, rev: 0, timers, debounceMs: 10,
    send: async (p, rev) => { running++; maxRunning = Math.max(maxRunning, running); await flushMicrotasks(); running--; return { ok: true, rev: rev + 1 }; },
  });
  for (let n = 0; n < 6; n++) { saver.edit(payload(n)); await timers.advance(11); }
  await saver.flush();
  assert.equal(maxRunning, 1);
});

test("a failed save keeps the edit, retries with back-off, then succeeds", async () => {
  const timers = fakeTimers();
  const storage = fakeStorage();
  let attempts = 0;
  const statuses = [];
  const saver = createSaver({
    imageId: 2, rev: 0, timers, storage, retryMs: [1000, 5000], debounceMs: 100,
    onStatus: (s) => statuses.push(s),
    send: async (p, rev) => { attempts++; if (attempts <= 2) throw new Error("offline"); return { ok: true, rev: rev + 1 }; },
  });
  saver.edit(payload(1));
  await timers.advance(100);
  assert.equal(saver.status, "error");
  assert.ok(storage.has(draftKey(2)), "the draft survives a failed save");
  await timers.advance(1000);
  assert.equal(attempts, 2);
  assert.equal(saver.status, "error");
  await timers.advance(5000);
  assert.equal(attempts, 3);
  assert.equal(saver.status, "saved");
  assert.equal(storage.has(draftKey(2)), false);
  assert.ok(statuses.includes("error") && statuses.at(-1) === "saved");
});

test("a revision conflict stops saving, keeps the draft, and reports the current revision", async () => {
  const timers = fakeTimers();
  const storage = fakeStorage();
  let detail = null;
  let calls = 0;
  const saver = createSaver({
    imageId: 3, rev: 0, timers, storage, debounceMs: 10,
    onStatus: (s, d) => { if (s === "conflict") detail = d; },
    send: async () => { calls++; return { conflict: true, currentRev: 4 }; },
  });
  saver.edit(payload(1));
  await timers.advance(20);
  assert.equal(saver.status, "conflict");
  assert.deepEqual(detail, { currentRev: 4 });
  assert.ok(storage.has(draftKey(3)));
  saver.edit(payload(2)); // ignored while stopped
  await timers.advance(1000);
  assert.equal(calls, 1);
  saver.reset(4); // the caller reloaded from the server
  assert.equal(saver.status, "saved");
  assert.equal(saver.rev, 4);
  assert.equal(storage.has(draftKey(3)), false);
  saver.edit(payload(3));
  await timers.advance(1000);
  assert.equal(calls, 2);
});

test("flush saves immediately and waits for completion", async () => {
  const timers = fakeTimers();
  const sent = [];
  const saver = createSaver({ imageId: 1, rev: 0, timers, debounceMs: 60000, send: async (p, rev) => { sent.push(p); return { ok: true, rev: rev + 1 }; } });
  saver.edit(payload(1));
  await saver.flush();
  assert.equal(sent.length, 1);
  assert.equal(saver.hasUnsavedChanges, false);
  await saver.flush(); // nothing pending: no extra request
  assert.equal(sent.length, 1);
});

test("draft helpers tolerate missing or broken storage", () => {
  assert.equal(readDraft({ getItem: () => { throw new Error("blocked"); } }, 1), null);
  assert.equal(readDraft({ getItem: () => "{not json" }, 1), null);
  assert.doesNotThrow(() => clearDraft({ removeItem: () => { throw new Error("blocked"); } }, 1));
  const saver = createSaver({ imageId: 1, rev: 0, storage: { setItem: () => { throw new Error("quota"); }, removeItem() {} }, timers: fakeTimers(), send: async (p, r) => ({ ok: true, rev: r + 1 }) });
  assert.doesNotThrow(() => saver.edit(payload(1))); // a full disk must not break editing
});

// ---- review findings (v0.2): hiding the page, rejected saves, drafts after a conflict -------------

test("flushNow (page hidden) and the debounce timer produce exactly ONE request, with the right revision", async () => {
  const timers = fakeTimers();
  const sent = [];
  const saver = createSaver({ imageId: 1, rev: 7, debounceMs: 400, timers, send: async (p, rev, options) => { sent.push({ rev, options }); return { ok: true, rev: rev + 1 }; } });
  saver.edit(payload(1));
  await saver.flushNow({ keepalive: true }); // what the page does on visibilitychange/pagehide
  await timers.advance(5000); // the debounce timer must not fire a second, stale request
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], { rev: 7, options: { keepalive: true } });
  assert.equal(saver.rev, 8);
  assert.equal(saver.status, "saved");
});

test("an edit after hiding the page is still saved (no false conflict, saving not stopped)", async () => {
  const timers = fakeTimers();
  const sent = [];
  const saver = createSaver({ imageId: 1, rev: 0, debounceMs: 100, timers, send: async (p, rev) => { sent.push([p, rev]); return { ok: true, rev: rev + 1 }; } });
  saver.edit(payload(1));
  await saver.flushNow({ keepalive: true });
  saver.edit(payload(2));
  await timers.advance(200);
  assert.deepEqual(sent.map(([, rev]) => rev), [0, 1]);
  assert.equal(saver.status, "saved");
});

test("flushNow while a save is already in flight does not send a duplicate", async () => {
  const timers = fakeTimers();
  let calls = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const saver = createSaver({ imageId: 1, rev: 0, debounceMs: 10, timers, send: async (p, rev) => { calls++; await gate; return { ok: true, rev: rev + 1 }; } });
  saver.edit(payload(1));
  await timers.advance(20);
  const again = saver.flushNow({ keepalive: true });
  release();
  await again;
  await flushMicrotasks();
  assert.equal(calls, 1);
});

test("after a conflict, further edits still go to the local draft (they are never silently lost)", async () => {
  const timers = fakeTimers();
  const storage = fakeStorage();
  const saver = createSaver({ imageId: 4, rev: 0, timers, storage, debounceMs: 10, send: async () => ({ conflict: true, currentRev: 9 }) });
  saver.edit(payload(1));
  await timers.advance(20);
  assert.equal(saver.status, "conflict");
  saver.edit(payload(2));
  saver.edit(payload(3));
  assert.deepEqual(readDraft(storage, 4).payload, payload(3));
  assert.equal(saver.hasUnsavedChanges, true);
});

test("a rejected save is reported with its reason, NOT retried, and the next edit tries again", async () => {
  const timers = fakeTimers();
  let calls = 0;
  let detail = null;
  const saver = createSaver({
    imageId: 5, rev: 0, timers, debounceMs: 10, retryMs: [50],
    onStatus: (s, d) => { if (s === "rejected") detail = d; },
    send: async (p, rev) => { calls++; return calls === 1 ? { rejected: true, message: "class missing" } : { ok: true, rev: rev + 1 }; },
  });
  saver.edit(payload(1));
  await timers.advance(20);
  assert.equal(saver.status, "rejected");
  assert.deepEqual(detail, { message: "class missing" });
  await timers.advance(10000); // no automatic retry
  assert.equal(calls, 1);
  assert.equal(saver.hasUnsavedChanges, true);
  saver.edit(payload(2)); // the user fixes something: try again
  await timers.advance(20);
  assert.equal(calls, 2);
  assert.equal(saver.status, "saved");
});

test("dispose stops everything: no sends after leaving", async () => {
  const timers = fakeTimers();
  let calls = 0;
  const saver = createSaver({ imageId: 1, rev: 0, timers, debounceMs: 10, send: async (p, rev) => { calls++; return { ok: true, rev: rev + 1 }; } });
  saver.edit(payload(1));
  saver.dispose();
  await timers.advance(1000);
  saver.edit(payload(2));
  await timers.advance(1000);
  await saver.flushNow();
  assert.equal(calls, 0);
});
