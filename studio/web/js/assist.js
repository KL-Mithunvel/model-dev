// AI assist panel and suggestion layer for the annotator (Stage 4.4).
// Suggestions come from /api/images/{id}/suggest and live ONLY here, in memory, until the user accepts
// them; accepting hands plain annotations to the annotator, which saves them like hand-drawn ones.
import { api, ApiError, watchJob } from "./api.js";
import { classFor, percent, shown, toAnnotations, withIds } from "./suggest.js";
import { el, plural } from "./ui.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const NEUTRAL_COLOUR = "#999999";
const MODES = [
  { id: "point", task: "segment_point", label: "Click an object" },
  { id: "text", task: "detect_text", label: "Describe objects" },
];
const svgEl = (tag, attrs = {}) => {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
};
const MB = 1_000_000;

/**
 * ctx: { imageId, classes(), activeClassId(), classById(id), newId, canAdd(n), addItems(items) -> ids,
 *        needClass(), repaint(), setTool(name), announce(text), toast(message, options) }
 */
export function createAssist(ctx) {
  const state = {
    backends: [], backendId: null, mode: "point", minScore: 0.5, suggestions: [], busy: false,
    text: "", loaded: false, error: "", download: null,
  };
  let disposed = false;

  const status = el("p", { class: "hint", role: "status" });
  const backendSelect = el("select", { class: "input", "aria-label": "Assist backend", "data-fk": "assist-backend", onchange: () => { state.backendId = backendSelect.value; syncControls(); } });
  const modeGroup = el("div", { class: "seg", role: "group", "aria-label": "Assist mode" });
  const textInput = el("input", { class: "input", type: "text", id: "assist-text", "data-fk": "assist-text", placeholder: "e.g. pallet, forklift", autocomplete: "off", "aria-label": "Describe the objects to find", oninput: () => { state.text = textInput.value; } });
  const findButton = el("button", { class: "btn btn-primary", type: "button", "data-fk": "assist-find", text: "Find", onclick: () => requestText() });
  const textRow = el("div", { class: "row" }, textInput, findButton);
  const pointHint = el("p", { class: "hint", text: "Click an object on the image (tool M); it is outlined as a suggestion." });
  const downloadButton = el("button", { class: "btn", type: "button", "data-fk": "assist-download", onclick: () => startDownload() });
  const slider = el("input", { type: "range", min: "0", max: "100", step: "5", value: "50", "data-fk": "assist-score", "aria-label": "Minimum score to show", oninput: () => { state.minScore = Number(slider.value) / 100; renderScore(); renderList(); ctx.repaint(); } });
  const scoreLabel = el("label", { class: "hint", for: "assist-score" });
  slider.id = "assist-score";
  const sliderRow = el("div", { class: "field" }, scoreLabel, slider);
  const list = el("ul", { class: "sug-list" });
  const acceptAll = el("button", { class: "btn btn-primary", type: "button", "data-fk": "assist-accept-all", onclick: () => accept(shown(state.suggestions, state.minScore)) });
  const rejectAll = el("button", { class: "btn", type: "button", "data-fk": "assist-reject-all", onclick: () => reject(state.suggestions.map((s) => s.id)) });
  const actions = el("div", { class: "row" }, acceptAll, rejectAll);
  const panel = el("div", { class: "a-section assist", "data-assist": "" }, el("h3", { text: "AI assist" }), status, backendSelect, modeGroup, pointHint, textRow, downloadButton, sliderRow, list, actions);

  const backend = () => state.backends.find((b) => b.id === state.backendId) ?? null;
  const usable = () => state.backends.filter((b) => b.available);
  const modeSupported = (mode) => Boolean(backend()?.tasks.includes(mode.task));

  function renderScore() {
    scoreLabel.textContent = `Show suggestions scoring ${percent(state.minScore)} or more`;
  }

  function syncControls() {
    const current = backend();
    status.textContent = state.error || (!state.loaded ? "Looking for assist backends…" : !state.backends.length ? "No assist backend is set up (ml.backends in config.yaml)."
      : current && !current.available ? current.reason
      : current?.simulated ? "Demo backend: results are made up, not real AI."
      : state.busy ? "Working…" : "Suggestions are never saved until you accept them.");
    backendSelect.hidden = state.backends.length < 2;
    backendSelect.replaceChildren(...state.backends.map((b) => el("option", { value: b.id, text: b.available ? b.name : `${b.name} (not available)`, selected: b.id === state.backendId })));
    modeGroup.replaceChildren(...MODES.filter(modeSupported).map((m) => el("button", { type: "button", "data-mode": m.id, text: m.label, "data-fk": `assist-mode:${m.id}`, "aria-pressed": String(m.id === state.mode), onclick: () => setMode(m.id) })));
    modeGroup.hidden = !current || modeGroup.children.length < 2;
    const ready = Boolean(current?.available) && !state.busy;
    pointHint.hidden = !(current?.available && state.mode === "point");
    textRow.hidden = !(current?.available && state.mode === "text");
    findButton.disabled = !ready;
    textInput.disabled = state.busy;
    const download = current?.can_download;
    downloadButton.hidden = !download;
    downloadButton.disabled = Boolean(state.download);
    downloadButton.textContent = state.download ? `Downloading… ${state.download}` : "Download model";
    renderScore();
    renderList();
  }

  function renderList() {
    const visible = shown(state.suggestions, state.minScore);
    sliderRow.hidden = actions.hidden = list.hidden = !state.suggestions.length;
    acceptAll.textContent = `Accept ${visible.length} shown`;
    acceptAll.disabled = !visible.length;
    rejectAll.textContent = "Reject all";
    list.replaceChildren(...visible.map((s) => {
      const classId = classFor(s, ctx.classes(), ctx.activeClassId());
      const colour = ctx.classById(classId)?.color ?? NEUTRAL_COLOUR;
      const name = s.label ?? (s.kind === "polygon" ? "outline" : "box");
      return el("li", { "data-suggestion": s.id },
        el("i", { class: "swatch-dot", style: `background:${colour}` }),
        el("span", { class: "grow", text: `${name} · ${percent(s.score)}` }),
        el("button", { class: "btn btn-quiet", type: "button", "data-fk": `sug-accept:${s.id}`, "aria-label": `Accept ${name} ${percent(s.score)}`, text: "Accept", onclick: () => accept([s]) }),
        el("button", { class: "btn btn-quiet", type: "button", "data-fk": `sug-reject:${s.id}`, "aria-label": `Reject ${name} ${percent(s.score)}`, text: "Reject", onclick: () => reject([s.id]) }));
    }));
    const hidden = state.suggestions.length - visible.length;
    if (hidden > 0) list.append(el("li", { class: "hint", text: `${plural(hidden, "suggestion")} hidden by the score filter.` }));
  }

  function setMode(mode) {
    state.mode = mode;
    if (mode === "point") ctx.setTool("assist");
    syncControls();
    if (mode === "text") textInput.focus();
  }

  // ---- requests -------------------------------------------------------------------------------
  async function ask(body, what) {
    const current = backend();
    if (!current?.available) { ctx.toast(current?.reason || "No assist backend is available.", { error: true }); return; }
    if (state.busy) return;
    state.busy = true;
    state.error = "";
    syncControls();
    try {
      const reply = await api(`/api/images/${ctx.imageId}/suggest`, { method: "POST", body: { backend: current.id, ...body } });
      if (disposed) return;
      state.suggestions = state.suggestions.concat(withIds(reply.suggestions, ctx.newId));
      const note = reply.dropped ? ` (${plural(reply.dropped, "invalid result")} ignored)` : "";
      if (!reply.suggestions.length) ctx.toast(`Nothing found for ${what}.`);
      else ctx.announce(`${plural(reply.suggestions.length, "suggestion")}${note}. Enter accepts, Escape rejects.`);
    } catch (error) {
      if (!disposed) ctx.toast(error instanceof ApiError ? error.message : "The suggestion could not be made.", { error: true });
    } finally {
      state.busy = false;
      if (!disposed) { syncControls(); ctx.repaint(); }
    }
  }

  /** A click in the assist tool: outline the object at this image point. */
  function requestPoint(point, positive = true) {
    if (state.mode !== "point") { ctx.toast("Switch to “Click an object” to outline by clicking.", {}); return; }
    return ask({ task: "segment_point", points: [[point.x, point.y, positive ? 1 : 0]], max_results: 1 }, "that click");
  }
  function requestText() {
    const text = textInput.value.trim();
    if (!text) { ctx.toast("Describe what to find first, for example “pallet, forklift”.", { error: true }); textInput.focus(); return; }
    return ask({ task: "detect_text", text }, `“${text}”`);
  }

  // ---- accept / reject ------------------------------------------------------------------------
  function accept(chosen) {
    if (!chosen.length) return;
    if (!ctx.classes().length) { ctx.needClass(); return; }
    if (!ctx.canAdd(chosen.length)) return;
    const { items, skipped } = toAnnotations(chosen, { classes: ctx.classes(), fallbackClassId: ctx.activeClassId(), newId: ctx.newId });
    if (!items.length) { ctx.needClass(); return; }
    ctx.addItems(items);
    const taken = new Set(chosen.map((s) => s.id));
    state.suggestions = state.suggestions.filter((s) => !taken.has(s.id));
    if (skipped) ctx.toast(`${plural(skipped, "suggestion")} had no class and were left out.`, { error: true });
    syncControls();
    ctx.repaint();
  }
  function reject(ids) {
    const gone = new Set(ids);
    if (!state.suggestions.some((s) => gone.has(s.id))) return;
    state.suggestions = state.suggestions.filter((s) => !gone.has(s.id));
    syncControls();
    ctx.repaint();
    ctx.announce("Suggestions rejected");
  }

  // ---- model download -------------------------------------------------------------------------
  async function startDownload() {
    const current = backend();
    if (!current) return;
    state.download = "starting";
    syncControls();
    try {
      const { job_id: jobId } = await api(`/api/ml/backends/${current.id}/download`, { method: "POST" });
      const job = await watchJob(jobId, (update) => {
        if (update.total) { state.download = `${Math.round((update.done / update.total) * 100)}% of ${Math.round(update.total / MB)} MB`; if (!disposed) syncControls(); }
      });
      if (job.state === "failed") throw new Error(job.error || "The download failed.");
      ctx.toast("Model downloaded. Assist is ready.");
    } catch (error) {
      ctx.toast(error.message, { error: true });
    } finally {
      state.download = null;
      if (!disposed) await load();
    }
  }

  async function load() {
    try {
      const reply = await api("/api/ml/backends");
      if (disposed) return;
      state.backends = reply.backends;
      state.minScore = reply.default_min_score;
      slider.value = String(Math.round(state.minScore * 100));
      state.backendId = state.backends.find((b) => b.id === state.backendId)?.id ?? (usable()[0] ?? state.backends[0])?.id ?? null;
      const first = MODES.find(modeSupported);
      if (first && !modeSupported(MODES.find((m) => m.id === state.mode))) state.mode = first.id;
      state.error = "";
    } catch (error) {
      state.error = error.message;
    }
    state.loaded = true;
    if (!disposed) syncControls();
  }

  // ---- drawing the suggestions on the image ---------------------------------------------------
  /** Append the visible suggestions to the overlay: dashed outlines, clickable only in the assist tool. */
  function draw(parent, scale) {
    const layer = svgEl("g", { class: "suggest-layer" });
    for (const s of shown(state.suggestions, state.minScore)) {
      const classId = classFor(s, ctx.classes(), ctx.activeClassId());
      const colour = ctx.classById(classId)?.color ?? NEUTRAL_COLOUR;
      const look = { fill: colour, "fill-opacity": 0.1, stroke: colour, "stroke-width": 2, "stroke-dasharray": "7 5", "vector-effect": "non-scaling-stroke" };
      const group = svgEl("g", { class: "suggestion", "data-suggest": s.id });
      let anchor;
      if (s.kind === "box") {
        group.append(svgEl("rect", { ...look, x: s.data.x, y: s.data.y, width: s.data.w, height: s.data.h }));
        anchor = [s.data.x, s.data.y];
      } else {
        group.append(svgEl("polygon", { ...look, points: s.data.points.map(([x, y]) => `${x},${y}`).join(" "), "stroke-linejoin": "round" }));
        anchor = s.data.points.reduce((best, p) => (p[1] < best[1] || (p[1] === best[1] && p[0] < best[0]) ? p : best));
      }
      const label = svgEl("text", { x: anchor[0] + 3 / scale, y: anchor[1] + 14 / scale, "font-size": 12 / scale });
      label.textContent = `${s.label ? `${s.label} ` : ""}${percent(s.score)}`;
      group.append(label);
      layer.append(group);
    }
    parent.append(layer);
  }

  const idAt = (node) => node?.closest?.("[data-suggest]")?.dataset.suggest ?? null;
  const find = (id) => state.suggestions.find((s) => s.id === id) ?? null;

  syncControls();
  load();

  return {
    panel,
    draw,
    requestPoint,
    idAt,
    acceptId: (id) => { const s = find(id); if (s) accept([s]); },
    acceptShown: () => accept(shown(state.suggestions, state.minScore)),
    rejectAll: () => reject(state.suggestions.map((s) => s.id)),
    hasSuggestions: () => state.suggestions.length > 0,
    refreshClasses: () => { renderList(); },
    dispose: () => { disposed = true; },
  };
}

