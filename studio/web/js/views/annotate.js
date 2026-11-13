// Annotator: draw, edit and label one image.
// Pure logic lives in geometry.js, editor.js, history.js and saver.js (all unit-tested); this file
// is the DOM, pointer and keyboard glue around them.
import { api, ApiError } from "../api.js";
import { openClassDialog } from "../classes.js";
import {
  addBox, appendFromServer, canMarkEmpty, cycle, deleteAnnotations, dropUnknownClasses,
  duplicateAnnotations, fromServer, makeIdFactory, moveAnnotations, resizeAnnotationsBy,
  resizeAnnotationTo, setClass, canTakeClass, setLabel, setMarkedEmpty, toPayload,
  addPolygon, insertVertex, moveVertex, removeVertex, simplifyAnnotation,
  addKeypoints, placeKeypoint, setKeypointVisibility,
} from "../editor.js";
import {
  HANDLES, HIDDEN, NOT_LABELLED, VISIBLE, boxFromPoints, clamp, defaultBox, defaultKeypoints,
  defaultPolygon, fitView, handlePoint, keypointsBounds, midpoint, nextVisibility, panBy,
  polygonArea, polygonBounds, polygonSelfIntersects, screenToImage, visibleRect, zoomAt,
} from "../geometry.js";
import { createHistory } from "../history.js";
import { limits } from "../limits.js";
import { clearDraft, createSaver, readDraft } from "../saver.js";
import { el, enableRadioArrows, icon, isTyping, plural, rovingTabindex, toast } from "../ui.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const HANDLE_SIZE_PX = 10; // size of a resize handle on screen, whatever the zoom
const MIN_DRAW_PX = 4; // a drag shorter than this on screen is a click, not a box
const DRAG_START_PX = 3; // a press must move this far before it moves a shape
const CLOSE_RADIUS_PX = 10; // clicking this close to the first point closes a polygon
const MIN_POINT_GAP_PX = 3; // a second click this close to the last point is a double-click, not a new point
const DOUBLE_CLICK_GUARD_MS = 450; // presses this soon after a polygon was closed are the 2nd half of a double-click
const POSE_PAD_PX = 8; // padding of the clickable box around a set of keypoints
const KEYPOINT_RADIUS_PX = 4.5;
const VISIBILITY_NAMES = ["not labelled", "hidden", "visible"];
const NUDGE = 1;
const NUDGE_BIG = 10;
const CURSORS = { nw: "nwse-resize", se: "nwse-resize", ne: "nesw-resize", sw: "nesw-resize", n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize" };
const STATUS_TEXT = { saved: "Saved", saving: "Saving…", dirty: "Unsaved changes", error: "Couldn’t save – retrying", conflict: "Changed elsewhere", rejected: "Couldn’t save – see message" };

const svgEl = (tag, attrs = {}) => {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
};

function safeStorage() {
  try {
    const storage = window.localStorage;
    storage.setItem("__studio_probe", "1");
    storage.removeItem("__studio_probe");
    return storage;
  } catch {
    return null; // private mode or blocked: autosave to the server still works
  }
}

const isLabelled = (state) => state.annotations.length > 0 || state.marked_empty || state.label_class_id !== null;

export async function mount(container, { setToolbar, navigate, projectId, imageId }) {
  const storage = safeStorage();
  const newId = makeIdFactory();
  const ui = { tool: "select", activeClass: null, selection: new Set(), view: { scale: 1, tx: 0, ty: 0 }, fitted: true, preview: null, draft: null, poly: null, kp: null, vertex: null, drag: null, space: false };
  let image = null;
  let classes = [];
  let neighbours = null;
  let stats = null;
  let history = null;
  let saver = null;
  let initialLabelled = false;
  let width = 0;
  let height = 0;
  const cleanups = [];
  const listen = (target, type, handler, options) => {
    target.addEventListener(type, handler, options);
    cleanups.push(() => target.removeEventListener(type, handler, options));
  };

  // ---- skeleton ---------------------------------------------------------------------------
  const toolstrip = el("div", { class: "toolstrip", role: "toolbar", "aria-label": "Tools", "aria-orientation": "vertical" });
  const viewport = el("div", { class: "viewport" });
  const stage = el("div", { class: "stage", tabindex: "0", role: "application", "aria-label": "Image canvas. B draws boxes, P draws polygons, K places keypoints, Enter drops a default shape in the middle, V selects, H or Space pans, A and D change image. Press ? for all shortcuts." }, viewport);
  const hud = el("div", { class: "hud", "aria-hidden": "true" });
  const kpHint = el("div", { class: "kp-hint", hidden: true });
  const banner = el("div", { class: "a-banner", role: "status", hidden: true });
  const live = el("div", { class: "sr-only", role: "status", "aria-live": "polite" });
  const inspector = el("aside", { class: "a-inspector", "aria-label": "Annotations" });
  const filmstrip = el("div", { class: "filmstrip", role: "list", "aria-label": "Images" });
  container.replaceChildren(
    el("div", { class: "annotator" }, toolstrip, el("div", { class: "stage-wrap" }, banner, stage, hud, kpHint), inspector, filmstrip, live),
  );
  // not a live region: it changes on every edit, which would be chatty. Problems are announced instead.
  const statusChip = el("span", { class: "chip save-chip", "data-status": "saved", text: STATUS_TEXT.saved });
  let statusBanner = false; // a banner that explains a save problem (hidden again once saved)

  const announce = (text) => { live.textContent = ""; setTimeout(() => { live.textContent = text; }, 30); };
  const showBanner = (message, actions = []) => {
    banner.replaceChildren(el("span", { text: message }), ...actions.map((a) => el("button", { class: "btn", type: "button", text: a.label, onclick: a.onClick })));
    banner.hidden = false;
  };
  const hideBanner = () => { banner.hidden = true; banner.replaceChildren(); };

  // ---- derived values ---------------------------------------------------------------------
  const current = () => ui.preview ?? history.present;
  const classById = (id) => classes.find((c) => c.id === id) ?? null;
  const activeClassId = () => (classById(ui.activeClass) ? ui.activeClass : (classes[0]?.id ?? null));
  const minBox = () => limits.min_box_px;
  const stageRect = () => stage.getBoundingClientRect();
  const stagePoint = (event) => { const r = stageRect(); return { sx: event.clientX - r.left, sy: event.clientY - r.top }; };
  const imagePoint = (event) => { const s = stagePoint(event); return { ...s, ...screenToImage(ui.view, s.sx, s.sy) }; };

  // ---- loading ----------------------------------------------------------------------------
  async function loadServerState() {
    const server = await api(`/api/images/${imageId}/annotations`);
    history = createHistory(fromServer(server, newId), { limit: limits.undo_limit });
    const rev = server.rev;
    if (saver) saver.dispose();
    saver = createSaver({
      imageId, rev, storage, debounceMs: limits.save_debounce_ms,
      onStatus: (status, detail) => {
        statusChip.textContent = STATUS_TEXT[status] ?? status;
        statusChip.dataset.status = status;
        if (status === "conflict") offerConflictChoice(detail);
        else if (status === "rejected") offerRejectedChoice(detail);
        else if (status === "saved" && statusBanner) { hideBanner(); statusBanner = false; }
        if (status === "error" || status === "conflict" || status === "rejected") announce(STATUS_TEXT[status]);
      },
      send: async (payload, sendRev, options = {}) => {
        try {
          const result = await api(`/api/images/${imageId}/annotations`, { method: "PUT", body: { ...payload, rev: sendRev }, keepalive: Boolean(options.keepalive) });
          return { ok: true, rev: result.rev };
        } catch (error) {
          if (error instanceof ApiError && error.status === 409 && error.data?.current_rev !== undefined) {
            return { conflict: true, currentRev: error.data.current_rev };
          }
          // The server understood and refused the content (for example a class that no longer exists).
          // Retrying the same request can never help, so report it instead of retrying forever.
          if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429) {
            return { rejected: true, message: error.message };
          }
          throw error;
        }
      },
    });
    ui.selection.clear();
    initialLabelled = isLabelled(history.present);
  }

  async function loadAll() {
    [image, classes, neighbours, stats] = await Promise.all([
      api(`/api/images/${imageId}`),
      api(`/api/projects/${projectId}/classes`),
      api(`/api/images/${imageId}/neighbours`),
      api(`/api/projects/${projectId}/annotation-stats`),
    ]);
    if (image.project_id !== projectId) throw new ApiError("That image is not in this project.", 404);
    width = image.width;
    height = image.height;
    await loadServerState();
  }

  try {
    await loadAll();
  } catch (error) {
    container.replaceChildren(
      el("div", { class: "empty", role: "alert" },
        el("h3", { text: error.status === 404 ? "Image not found" : "Could not open this image" }),
        el("p", { text: error.message }),
        el("a", { class: "btn btn-primary", href: `#/projects/${projectId}`, text: "Back to the gallery" })),
    );
    setToolbar({ title: "Image" });
    return () => {};
  }

  // ---- image and overlay ------------------------------------------------------------------
  const photo = el("img", { class: "photo", src: image.file_url, alt: `Image ${image.original_name}`, draggable: "false", width: String(width), height: String(height) });
  const svg = svgEl("svg", { class: "overlay", viewBox: `0 0 ${width} ${height}`, width, height });
  viewport.style.width = `${width}px`;
  viewport.style.height = `${height}px`;
  viewport.append(photo, svg);
  photo.decode().then(() => {
    if (photo.naturalWidth !== width || photo.naturalHeight !== height) {
      console.error(`Image size mismatch: file is ${photo.naturalWidth}x${photo.naturalHeight}, database says ${width}x${height}`);
      toast("This image’s size does not match what was imported. Annotations may be misplaced.", { error: true });
    }
  }).catch(() => toast("The image could not be displayed.", { error: true }));

  function applyView() {
    const { scale, tx, ty } = ui.view;
    viewport.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    renderShapes();
    updateHud();
  }
  function fit() {
    const r = stageRect();
    if (r.width < 50 || r.height < 50) return;
    ui.view = fitView(r.width, r.height, width, height);
    ui.fitted = true;
    applyView();
  }
  function zoomStep(factor) {
    const r = stageRect();
    ui.view = zoomAt(ui.view, factor, r.width / 2, r.height / 2);
    ui.fitted = false;
    applyView();
  }
  function updateHud(point = null) {
    const zoom = `${Math.round(ui.view.scale * 100)}%`;
    hud.textContent = point ? `${zoom} · ${Math.round(point.x)}, ${Math.round(point.y)}` : zoom;
  }
  const observer = new ResizeObserver(() => { if (ui.fitted) fit(); });
  observer.observe(stage);
  cleanups.push(() => observer.disconnect());

  // ---- rendering --------------------------------------------------------------------------
  let shapeNodes = new Map(); // annotation id -> { rect, label }
  let handleNodes = new Map(); // handle name -> rect
  let draftLayer = null; // <g> holding the polygon being drawn

  const pointsAttr = (points) => points.map(([x, y]) => `${x},${y}`).join(" ");
  const MAX_MID_HANDLES = 150; // beyond this many points the edge-midpoint handles only add clutter and cost

  /** Position the main shape node and its label for one annotation (box or polygon). */
  function placeShape(nodes, a, scale) {
    if (a.kind === "box") {
      nodes.rect.setAttribute("x", a.data.x);
      nodes.rect.setAttribute("y", a.data.y);
      nodes.rect.setAttribute("width", a.data.w);
      nodes.rect.setAttribute("height", a.data.h);
      nodes.label.setAttribute("x", a.data.x + 3 / scale);
      nodes.label.setAttribute("y", a.data.y + 14 / scale);
    } else if (a.kind === "keypoints") {
      const bounds = keypointsBounds(a.data.points);
      if (nodes.shown !== a.data || nodes.scale !== scale || nodes.selected !== ui.selection.has(a.id)) {
        nodes.shown = a.data; nodes.scale = scale; nodes.selected = ui.selection.has(a.id);
        drawPose(nodes.rect, a, bounds, scale);
      }
      nodes.label.setAttribute("x", (bounds ? bounds.minX - POSE_PAD_PX / scale : 0) + 3 / scale);
      // Above the pose's box so the text does not cover the first point; inside it only when
      // the pose touches the top of the image.
      const top = bounds ? bounds.minY - POSE_PAD_PX / scale : 0;
      nodes.label.setAttribute("y", top >= 18 / scale ? top - 4 / scale : top + 14 / scale);
    } else {
      nodes.rect.setAttribute("points", pointsAttr(a.data.points));
      const bounds = polygonBounds(a.data.points);
      nodes.label.setAttribute("x", bounds.minX + 3 / scale);
      nodes.label.setAttribute("y", bounds.minY + 14 / scale);
    }
  }

  /** The skeleton of a set of keypoints: a clickable box, the edges, then the points on top. */
  function drawPose(group, a, bounds, scale) {
    const color = classById(a.class_id)?.color ?? "#999999";
    const selected = ui.selection.has(a.id);
    const points = a.data.points;
    const kids = [];
    if (bounds) {
      const pad = POSE_PAD_PX / scale;
      kids.push(svgEl("rect", { class: "pose-box", x: bounds.minX - pad, y: bounds.minY - pad, width: bounds.w + 2 * pad, height: bounds.h + 2 * pad, fill: color, "fill-opacity": selected ? 0.18 : 0.06, stroke: selected ? color : "none", "stroke-width": 1.5, "stroke-dasharray": "5 4", "vector-effect": "non-scaling-stroke" }));
    }
    for (const [i, j] of classById(a.class_id)?.skeleton?.edges ?? []) {
      const from = points[i];
      const to = points[j];
      if (!from || !to || from[2] === NOT_LABELLED || to[2] === NOT_LABELLED) continue;
      kids.push(svgEl("line", { x1: from[0], y1: from[1], x2: to[0], y2: to[1], stroke: color, "stroke-width": 2, "stroke-dasharray": from[2] === HIDDEN || to[2] === HIDDEN ? "4 3" : "none", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
    }
    for (const [x, y, v] of points) {
      if (v === NOT_LABELLED) continue;
      kids.push(svgEl("circle", { class: "kp-dot", cx: x, cy: y, r: KEYPOINT_RADIUS_PX / scale, fill: v === VISIBLE ? color : "none", stroke: v === VISIBLE ? "#fff" : color, "stroke-width": 1.5, "stroke-dasharray": v === HIDDEN ? "2 2" : "none", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
    }
    group.replaceChildren(...kids);
  }

  function placeVertexHandles(points) {
    const size = HANDLE_SIZE_PX / ui.view.scale;
    points.forEach(([x, y], i) => {
      const vertex = handleNodes.get(`v${i}`);
      if (vertex) { vertex.setAttribute("x", x - size / 2); vertex.setAttribute("y", y - size / 2); }
      const mid = handleNodes.get(`m${i}`);
      if (mid) {
        const [mx, my] = midpoint(points[i], points[(i + 1) % points.length]);
        mid.setAttribute("cx", mx);
        mid.setAttribute("cy", my);
      }
    });
  }

  /** While dragging: move the existing nodes instead of rebuilding all of them (keeps 200+ shapes smooth). */
  function updateGeometry() {
    const state = current();
    const scale = ui.view.scale;
    for (const a of state.annotations) {
      const nodes = shapeNodes.get(a.id);
      if (nodes) placeShape(nodes, a, scale);
    }
    const chosen = state.annotations.filter((a) => ui.selection.has(a.id));
    if (chosen.length !== 1) return;
    if (chosen[0].kind === "box") {
      const size = HANDLE_SIZE_PX / scale;
      for (const [handle, node] of handleNodes) {
        const p = handlePoint(chosen[0].data, handle);
        node.setAttribute("x", p.x - size / 2);
        node.setAttribute("y", p.y - size / 2);
      }
    } else if (chosen[0].kind === "polygon") {
      placeVertexHandles(chosen[0].data.points);
    } else if (chosen[0].kind === "keypoints") {
      chosen[0].data.points.forEach(([x, y], i) => {
        const node = handleNodes.get(`k${i}`);
        if (node) { node.setAttribute("cx", x); node.setAttribute("cy", y); }
      });
    }
  }

  function renderShapes() {
    pruneVertex(); // a cancelled drag can leave a selected point that no longer exists
    const state = current();
    const scale = ui.view.scale;
    shapeNodes = new Map();
    handleNodes = new Map();
    svg.replaceChildren();
    for (const a of state.annotations) {
      if (a.kind !== "box" && a.kind !== "polygon" && a.kind !== "keypoints") continue;
      const color = classById(a.class_id)?.color ?? "#999999";
      const selected = ui.selection.has(a.id);
      const group = svgEl("g", { class: `shape${selected ? " selected" : ""}`, "data-id": a.id });
      const look = { fill: color, "fill-opacity": selected ? 0.3 : 0.14, stroke: color, "stroke-width": selected ? 3 : 2, "vector-effect": "non-scaling-stroke" };
      const main = a.kind === "box" ? svgEl("rect", look) : a.kind === "keypoints" ? svgEl("g", { class: "pose" }) : svgEl("polygon", { ...look, "stroke-linejoin": "round" });
      const label = svgEl("text", { "font-size": 12 / scale });
      label.textContent = classById(a.class_id)?.name ?? "?";
      group.append(main, label);
      svg.append(group);
      const nodes = { rect: main, label };
      shapeNodes.set(a.id, nodes);
      placeShape(nodes, a, scale);
    }
    const chosen = state.annotations.filter((a) => ui.selection.has(a.id));
    if (chosen.length === 1 && chosen[0].kind === "box") {
      const a = chosen[0];
      const size = HANDLE_SIZE_PX / scale;
      for (const handle of HANDLES) {
        const p = handlePoint(a.data, handle);
        const node = svgEl("rect", { x: p.x - size / 2, y: p.y - size / 2, width: size, height: size, class: "handle", "data-handle": handle, "data-id": a.id, "stroke-width": 1.5, "vector-effect": "non-scaling-stroke", style: `cursor:${CURSORS[handle]}` });
        handleNodes.set(handle, node);
        svg.append(node);
      }
    } else if (chosen.length === 1 && chosen[0].kind === "polygon") {
      const a = chosen[0];
      const points = a.data.points;
      const size = HANDLE_SIZE_PX / scale;
      if (points.length <= MAX_MID_HANDLES) {
        points.forEach((_, i) => {
          const mid = svgEl("circle", { r: (size * 0.35), class: "handle mid", "data-mid": i, "data-id": a.id, "stroke-width": 1.5, "vector-effect": "non-scaling-stroke", style: "cursor:copy" });
          handleNodes.set(`m${i}`, mid);
          svg.append(mid);
        });
      }
      points.forEach((_, i) => {
        const active = ui.vertex && ui.vertex.id === a.id && ui.vertex.index === i;
        const vertex = svgEl("rect", { width: size, height: size, class: `handle vertex${active ? " active" : ""}`, "data-vertex": i, "data-id": a.id, "stroke-width": 1.5, "vector-effect": "non-scaling-stroke", style: "cursor:move" });
        handleNodes.set(`v${i}`, vertex);
        svg.append(vertex);
      });
      placeVertexHandles(points);
    } else if (chosen.length === 1 && chosen[0].kind === "keypoints") {
      const a = chosen[0];
      a.data.points.forEach(([x, y, v], i) => {
        if (v === NOT_LABELLED) return;
        const active = ui.vertex && ui.vertex.id === a.id && ui.vertex.index === i;
        const node = svgEl("circle", { cx: x, cy: y, r: (KEYPOINT_RADIUS_PX + 3) / scale, class: `handle kp-handle${active ? " active" : ""}`, "data-kp": i, "data-id": a.id, "stroke-width": 2, "vector-effect": "non-scaling-stroke", style: "cursor:move" });
        handleNodes.set(`k${i}`, node);
        svg.append(node);
      });
    }
    if (ui.draft) {
      const color = classById(activeClassId())?.color ?? "#999999";
      svg.append(svgEl("rect", { x: ui.draft.x, y: ui.draft.y, width: ui.draft.w, height: ui.draft.h, fill: color, "fill-opacity": 0.2, stroke: color, "stroke-width": 2, "stroke-dasharray": "6 4", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
    }
    draftLayer = svgEl("g", { "pointer-events": "none" });
    svg.append(draftLayer);
    renderPolygonDraft();
  }

  /** The polygon being drawn, in its own layer so moving the pointer never rebuilds the real shapes. */
  function renderPolygonDraft() {
    if (!draftLayer) return;
    draftLayer.replaceChildren();
    renderKeypointDraft();
    if (!ui.poly || !ui.poly.points.length) return;
    const scale = ui.view.scale;
    const color = classById(activeClassId())?.color ?? "#999999";
    const points = ui.poly.points;
    const all = ui.poly.cursor ? [...points, ui.poly.cursor] : points;
    if (all.length >= 3) draftLayer.append(svgEl("polygon", { points: pointsAttr(all), fill: color, "fill-opacity": 0.12 }));
    draftLayer.append(svgEl("polyline", { points: pointsAttr(all), fill: "none", stroke: color, "stroke-width": 2, "stroke-dasharray": "6 4", "vector-effect": "non-scaling-stroke" }));
    const closable = points.length >= 3;
    const near = closable && ui.poly.cursor && Math.hypot(ui.poly.cursor[0] - points[0][0], ui.poly.cursor[1] - points[0][1]) * scale <= CLOSE_RADIUS_PX;
    points.forEach(([x, y], i) => {
      const first = i === 0 && closable;
      draftLayer.append(svgEl("circle", { cx: x, cy: y, r: (first ? 7 : 4) / scale, fill: color, class: `poly-dot${first ? " close-target" : ""}${first && near ? " hot" : ""}` }));
    });
  }

  /** The keypoints being placed, and the line that says which point comes next. */
  function renderKeypointDraft() {
    const kp = ui.kp;
    kpHint.hidden = !kp;
    if (!kp) return;
    const cls = classById(kp.classId);
    const names = cls?.skeleton?.names ?? [];
    const scale = ui.view.scale;
    const color = cls?.color ?? "#999999";
    for (const [i, j] of cls?.skeleton?.edges ?? []) {
      const from = kp.points[i];
      const to = kp.points[j];
      if (from && to && from[2] && to[2]) draftLayer.append(svgEl("line", { x1: from[0], y1: from[1], x2: to[0], y2: to[1], stroke: color, "stroke-width": 2, "vector-effect": "non-scaling-stroke" }));
    }
    for (const [x, y, v] of kp.points) {
      if (v) draftLayer.append(svgEl("circle", { cx: x, cy: y, r: KEYPOINT_RADIUS_PX / scale, fill: v === VISIBLE ? color : "none", stroke: v === VISIBLE ? "#fff" : color, "stroke-width": 1.5, "stroke-dasharray": v === HIDDEN ? "2 2" : "none", "vector-effect": "non-scaling-stroke" }));
    }
    const name = names[kp.next] ?? `point ${kp.next + 1}`;
    kpHint.textContent = `Place “${name}” (${kp.next + 1} of ${kp.points.length}) · click = visible · Shift+click = hidden · X = skip · Backspace = back · Enter = finish · Esc = cancel`;
  }

  /** Rebuild `host` with `build()` and put keyboard focus back on the element that had it. */
  function rebuild(host, build) {
    const key = document.activeElement?.closest?.("[data-fk]")?.dataset.fk;
    host.replaceChildren(...build());
    if (key) host.querySelector(`[data-fk="${CSS.escape(key)}"]`)?.focus({ preventScroll: true });
  }
  const fk = (key) => ({ "data-fk": key });

  function renderToolstrip() {
    const tool = (name, label, iconName, key) => el("button", { class: "btn btn-quiet btn-icon", type: "button", "aria-label": `${label} (${key})`, title: `${label} (${key})`, "aria-pressed": String(ui.tool === name), ...fk(`tool:${name}`), onclick: () => setTool(name) }, icon(iconName));
    const plain = (label, iconName, handler, disabled = false) => el("button", { class: "btn btn-quiet btn-icon", type: "button", "aria-label": label, title: label, disabled, ...fk(`btn:${label}`), onclick: handler }, icon(iconName));
    rebuild(toolstrip, () => [
      tool("select", "Select", "cursor", "V"), tool("box", "Draw box", "box", "B"), tool("polygon", "Draw polygon", "polygon", "P"), tool("keypoints", "Place keypoints", "keypoints", "K"), tool("pan", "Pan", "move", "H"),
      el("hr", { class: "tool-sep" }),
      plain("Zoom in (+)", "zoom-in", () => zoomStep(1.25)), plain("Zoom out (−)", "zoom-out", () => zoomStep(0.8)), plain("Fit to window (0)", "fit", fit),
      el("hr", { class: "tool-sep" }),
      plain("Undo (Ctrl+Z)", "undo", undo, !history.canUndo), plain("Redo (Ctrl+Shift+Z)", "redo", redo, !history.canRedo),
    ]);
    stage.dataset.tool = ui.tool;
  }

  function renderInspector() {
    const state = current();
    const total = stats.images;
    const labelledNow = stats.labelled + (isLabelled(state) ? 1 : 0) - (initialLabelled ? 1 : 0);
    rebuild(inspector, () => {
      const parts = [];
      parts.push(
        el("div", { class: "a-section" },
          el("h2", { class: "a-title", text: image.original_name }),
          el("p", { class: "muted num", text: `Image ${neighbours.index} of ${neighbours.total} · ${labelledNow.toLocaleString()} of ${total.toLocaleString()} labelled` }),
          el("div", { class: "progress", role: "progressbar", "aria-label": "Labelling progress", "aria-valuemin": "0", "aria-valuemax": String(total), "aria-valuenow": String(labelledNow) }, el("div", { style: `width:${total ? (labelledNow / total) * 100 : 0}%` }))),
      );
      // image label (single-label classification)
      parts.push(
        el("div", { class: "a-section" }, el("h3", { text: "Image label" }),
          el("div", { class: "radio-list", role: "radiogroup", "aria-label": "Image label" },
            ...classes.map((c, i) => el("button", { class: "radio", type: "button", role: "radio", "aria-checked": String(state.label_class_id === c.id), ...fk(`label:${c.id}`), onclick: () => toggleLabel(c.id) },
              el("i", { class: "swatch-dot", style: `background:${c.color}` }), c.name, i < 9 ? el("kbd", { text: `⇧${i + 1}` }) : null)),
            classes.length ? null : el("span", { class: "hint", text: "Add a class to label whole images." }))),
      );
      // classes
      const counts = new Map();
      for (const a of state.annotations) counts.set(a.class_id, (counts.get(a.class_id) ?? 0) + 1);
      parts.push(
        el("div", { class: "a-section" },
          el("div", { class: "a-row-head" }, el("h3", { text: "Classes" }), el("button", { class: "btn", type: "button", ...fk("add-class"), onclick: addClass }, icon("plus"), "Add")),
          classes.length
            ? el("ul", { class: "class-list" }, ...classes.map((c, i) => el("li", {},
                el("button", { class: "class-row", type: "button", "aria-pressed": String(activeClassId() === c.id), ...fk(`class:${c.id}`), onclick: () => chooseClass(c.id) },
                  el("i", { class: "swatch-dot", style: `background:${c.color}` }), el("span", { class: "grow", text: c.name }), el("span", { class: "muted num", text: String(counts.get(c.id) ?? 0) }), i < 9 ? el("kbd", { text: String(i + 1) }) : null),
                el("button", { class: "btn btn-quiet btn-icon", type: "button", "aria-label": `Edit class ${c.name}`, ...fk(`edit-class:${c.id}`), onclick: () => editClass(c) }, icon("edit")))))
            : el("p", { class: "hint", text: "No classes yet. Add one to start drawing boxes." })),
      );
      // annotations list
      parts.push(
        el("div", { class: "a-section" }, el("h3", { text: `Annotations (${state.annotations.length})` }),
          state.annotations.length
            ? el("ul", { class: "ann-list" }, ...state.annotations.map((a, i) => el("li", {},
                el("button", { class: "ann-row", type: "button", "aria-pressed": String(ui.selection.has(a.id)), ...fk(`ann:${a.id}`), onclick: (event) => selectFromList(a.id, event) },
                  el("i", { class: "swatch-dot", style: `background:${classById(a.class_id)?.color ?? "#999"}` }), annotationLabel(a, i)),
                el("button", { class: "btn btn-quiet btn-icon", type: "button", "aria-label": `Delete annotation ${i + 1}`, ...fk(`del:${a.id}`), onclick: () => deleteIds([a.id]) }, icon("trash")))))
            : el("p", { class: "hint", text: state.marked_empty ? "Marked as having no objects." : "Nothing drawn yet." })),
      );
      // the points of the selected set of keypoints
      const pose = selectedPointShape();
      if (pose && pose.kind === "keypoints") {
        parts.push(
          el("div", { class: "a-section" }, el("h3", { text: "Points" }),
            el("ul", { class: "kp-list" }, ...pose.data.points.map(([, , v], i) => el("li", {},
              el("button", { class: "ann-row", type: "button", "aria-pressed": String(Boolean(ui.vertex && ui.vertex.id === pose.id && ui.vertex.index === i)), disabled: v === NOT_LABELLED, ...fk(`kp:${i}`), onclick: () => { ui.vertex = { id: pose.id, index: i }; renderShapes(); renderInspector(); } },
                el("span", { class: "grow", text: pointName(pose, i) })),
              el("button", { class: "btn btn-quiet kp-state", type: "button", "data-v": String(v), "aria-label": `${pointName(pose, i)}: ${VISIBILITY_NAMES[v]}. Change`, ...fk(`kpv:${i}`), onclick: () => cycleKeypoint(pose.id, i) }, VISIBILITY_NAMES[v]))))),
        );
      }
      // image-level actions
      parts.push(
        el("div", { class: "a-section a-actions" },
          el("button", { class: "btn", type: "button", "aria-pressed": String(state.marked_empty), ...fk("no-objects"), onclick: toggleEmpty }, icon("check"), "No objects ", el("kbd", { text: "E" })),
          el("button", { class: "btn", type: "button", disabled: neighbours.previous === null, ...fk("repeat"), onclick: repeatPrevious }, icon("copy"), "Repeat previous image"),
          ...(selectedPolygon() ? [el("button", { class: "btn", type: "button", ...fk("simplify"), onclick: simplifySelected }, icon("polygon"), "Simplify polygon")] : []),
        ),
      );
      return parts;
    });
  }

  function wireRadioGroups() {
    for (const group of inspector.querySelectorAll(".radio-list")) {
      rovingTabindex(group);
      enableRadioArrows(group);
    }
  }

  function renderFilmstrip(items) {
    filmstrip.replaceChildren(
      ...items.map((item) => el("div", { role: "listitem", class: "film-cell" },
        el("button", { class: "film-item", type: "button", "aria-label": `${item.original_name}${item.id === imageId ? " (current)" : ""}`, ...(item.id === imageId ? { "aria-current": "true" } : {}), "data-id": String(item.id), "data-labelled": String(item.annotation_count > 0 || item.marked_empty || item.label_class_id !== null), onclick: () => go(item.id) },
          el("img", { src: item.thumb_url, alt: "", draggable: "false", loading: "lazy" })))),
    );
    filmstrip.querySelector("[aria-current]")?.scrollIntoView({ inline: "center", block: "nearest" });
  }
  async function loadFilmstrip() {
    const size = limits.filmstrip_size;
    const start = Math.max(0, Math.min(neighbours.index - 1 - Math.floor(size / 2), neighbours.total - size));
    try {
      const page = await api(`/api/projects/${projectId}/images?offset=${start}&limit=${size}`);
      renderFilmstrip(page.items);
    } catch {
      /* the filmstrip is a convenience; the annotator works without it */
    }
  }
  function updateFilmDot() {
    const dot = filmstrip.querySelector("[aria-current]");
    if (dot) dot.dataset.labelled = String(isLabelled(history.present));
  }

  function pruneVertex() {
    if (!ui.vertex) return;
    const shape = selectedPointShape();
    if (!shape || shape.id !== ui.vertex.id || ui.vertex.index >= shape.data.points.length) { ui.vertex = null; return; }
    if (shape.kind === "keypoints" && shape.data.points[ui.vertex.index][2] === NOT_LABELLED) ui.vertex = null;
  }

  function renderAll() {
    pruneVertex();
    renderShapes();
    renderToolstrip();
    renderInspector();
    wireRadioGroups();
    updateFilmDot();
  }

  // ---- editing ----------------------------------------------------------------------------
  function commit(next, options = {}) {
    ui.preview = null;
    const changed = history.push(next, options);
    const present = new Set(history.present.annotations.map((a) => a.id));
    for (const id of [...ui.selection]) if (!present.has(id)) ui.selection.delete(id);
    if (changed) saver.edit(toPayload(history.present));
    renderAll();
    return changed;
  }
  function undo() {
    if (ui.poly && ui.poly.points.length) { removeLastPolygonPoint(); return; } // Ctrl+Z while drawing
    if (ui.kp) { removeLastKeypoint(); return; }
    if (!history.undo()) return;
    ui.preview = null;
    afterHistoryMove("Undone");
  }
  function redo() {
    if (!history.redo()) return;
    ui.preview = null;
    afterHistoryMove("Redone");
  }
  function afterHistoryMove(message) {
    const present = new Set(history.present.annotations.map((a) => a.id));
    for (const id of [...ui.selection]) if (!present.has(id)) ui.selection.delete(id);
    saver.edit(toPayload(history.present));
    renderAll();
    announce(message);
  }
  /** True (with a message) while a polygon or a set of keypoints is half drawn: leaving would throw it away. */
  function blockWhileDrawing() {
    const what = ui.poly?.points.length ? "polygon" : ui.kp ? "keypoints" : null;
    if (!what) return false;
    toast(`Finish the ${what} (Enter) or cancel it (Esc) first.`, { error: true });
    return true;
  }
  function setTool(name) {
    if (name !== ui.tool && blockWhileDrawing()) return;
    ui.tool = name;
    renderToolstrip();
    announce(`${{ box: "Box", polygon: "Polygon", keypoints: "Keypoints", pan: "Pan" }[name] ?? "Select"} tool`);
    stage.focus({ preventScroll: true }); // so Enter / arrows / [ ] go to the canvas, not to the tool button
  }
  function needClass() {
    toast("Add a class first, then draw.", { error: true });
    addClass();
  }
  function canAdd(count = 1) {
    if (history.present.annotations.length + count <= limits.max_annotations) return true;
    toast(`An image can have at most ${limits.max_annotations} annotations.`, { error: true });
    return false;
  }
  function deleteIds(ids) {
    if (!ids.length) return;
    commit(deleteAnnotations(history.present, ids));
    announce(`${plural(ids.length, "annotation")} deleted`);
  }
  function deleteSelection() { deleteIds([...ui.selection]); }
  function duplicateSelection() {
    if (!ui.selection.size || !canAdd(ui.selection.size)) return;
    const { state, ids } = duplicateAnnotations(history.present, [...ui.selection], newId, 10, width, height);
    commit(state);
    ui.selection = new Set(ids);
    renderAll();
    announce(`${plural(ids.length, "annotation")} duplicated`);
  }
  function chooseClass(classId) {
    ui.activeClass = classId;
    if (ui.selection.size) {
      const length = classById(classId)?.skeleton?.names?.length ?? null;
      const ids = [...ui.selection];
      const blocked = history.present.annotations.filter((a) => ids.includes(a.id) && !canTakeClass(a, length));
      if (blocked.length) {
        toast(
          `${plural(blocked.length, "keypoint set")} keep${blocked.length === 1 ? "s" : ""} the old class: “${classById(classId)?.name}” has a different number of points.`,
          { error: true },
        );
      }
      if (blocked.length < ids.length) commit(setClass(history.present, ids, classId, length));
    } else renderInspector();
    announce(`Class ${classById(classId)?.name}`);
  }
  function toggleLabel(classId) {
    commit(setLabel(history.present, history.present.label_class_id === classId ? null : classId));
  }
  function toggleEmpty() {
    if (blockWhileDrawing()) return;
    const state = history.present;
    if (!state.marked_empty && !canMarkEmpty(state)) {
      toast("This image has annotations. Delete them first to mark it as having no objects.", { error: true });
      return;
    }
    commit(setMarkedEmpty(state, !state.marked_empty));
    announce(history.present.marked_empty ? "Marked as no objects" : "No longer marked as no objects");
  }
  function selectFromList(id, event) {
    if (event.shiftKey || event.ctrlKey || event.metaKey) {
      if (ui.selection.has(id)) ui.selection.delete(id); else ui.selection.add(id);
    } else {
      ui.selection = new Set([id]);
    }
    renderAll();
  }
  function nudge(dx, dy, resize) {
    const ids = [...ui.selection];
    if (!ids.length) return;
    const state = history.present;
    commit(resize ? resizeAnnotationsBy(state, ids, dx, dy, width, height, minBox()) : moveAnnotations(state, ids, dx, dy, width, height), { key: resize ? "resize" : "nudge" });
  }
  function boxAtCentre() {
    const classId = activeClassId();
    if (classId === null) { needClass(); return; }
    if (!canAdd()) return;
    const r = stageRect();
    const visible = visibleRect(ui.view, r.width, r.height, width, height);
    const box = defaultBox(visible.x + visible.w / 2, visible.y + visible.h / 2, visible.w, visible.h, width, height);
    const id = newId();
    commit(addBox(history.present, id, classId, box));
    ui.selection = new Set([id]);
    renderAll();
    announce("Box added. Use the arrow keys to move it and Alt with the arrows to resize.");
  }
  // ---- polygons ---------------------------------------------------------------------------
  let lastClosedAt = -1e9;
  let lastClosedPoint = [0, 0];
  const screenGap = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]) * ui.view.scale;

  function addPolygonPoint(p) {
    const point = [Math.min(Math.max(p.x, 0), width), Math.min(Math.max(p.y, 0), height)];
    // 2nd half of a double-click that just closed a polygon: same spot, moments later
    if (!ui.poly && performance.now() - lastClosedAt < DOUBLE_CLICK_GUARD_MS && screenGap(point, lastClosedPoint) <= CLOSE_RADIUS_PX) return;
    if (!ui.poly) ui.poly = { points: [], cursor: null };
    const points = ui.poly.points;
    if (points.length >= 3 && screenGap(point, points[0]) <= CLOSE_RADIUS_PX) { finishPolygon(); return; }
    if (points.length && screenGap(point, points[points.length - 1]) < MIN_POINT_GAP_PX) return; // double-click
    points.push(point);
    ui.poly.cursor = point;
    renderShapes();
    announce(`Point ${points.length}`);
  }

  function removeLastPolygonPoint() {
    if (!ui.poly) return;
    ui.poly.points.pop();
    if (!ui.poly.points.length) ui.poly = null;
    renderShapes();
  }

  function finishPolygon() {
    const poly = ui.poly;
    if (!poly) return;
    if (poly.points.length < 3) { toast("A polygon needs at least 3 points. Keep clicking to add more.", { error: true }); return; }
    if (polygonArea(poly.points) < limits.min_polygon_area_px) { toast("That polygon is too flat or small. Add points that enclose some area.", { error: true }); return; }
    if (!canAdd()) { ui.poly = null; renderShapes(); return; }
    const id = newId();
    const points = poly.points;
    ui.poly = null;
    lastClosedAt = performance.now();
    lastClosedPoint = points[0];
    commit(addPolygon(history.present, id, activeClassId(), points));
    ui.selection = new Set([id]);
    renderAll();
    announce(`Polygon added with ${points.length} points`);
    if (polygonSelfIntersects(points)) toast("This polygon crosses itself. Drag its points to fix it.");
  }

  function polygonAtCentre() {
    const classId = activeClassId();
    if (classId === null) { needClass(); return; }
    if (!canAdd()) return;
    const r = stageRect();
    const visible = visibleRect(ui.view, r.width, r.height, width, height);
    const points = defaultPolygon(visible.x + visible.w / 2, visible.y + visible.h / 2, visible.w, visible.h, width, height);
    const id = newId();
    commit(addPolygon(history.present, id, classId, points));
    ui.selection = new Set([id]);
    renderAll();
    announce("Polygon added. Press ] to select a point, then use the arrow keys to move it.");
  }

  function selectedPolygon() {
    if (ui.selection.size !== 1) return null;
    const id = [...ui.selection][0];
    const found = current().annotations.find((a) => a.id === id);
    return found && found.kind === "polygon" ? found : null;
  }

  /** The selected polygon or set of keypoints (the shapes whose points can be picked one by one). */
  function selectedPointShape() {
    if (ui.selection.size !== 1) return null;
    const id = [...ui.selection][0];
    const found = current().annotations.find((a) => a.id === id);
    return found && (found.kind === "polygon" || found.kind === "keypoints") ? found : null;
  }
  const pointName = (shape, index) => classById(shape.class_id)?.skeleton?.names?.[index] ?? `Point ${index + 1}`;

  function stepVertex(direction) {
    const shape = selectedPointShape();
    if (!shape) return false;
    const points = shape.data.points;
    const usable = points.map((_, i) => i).filter((i) => shape.kind === "polygon" || points[i][2] !== NOT_LABELLED);
    if (!usable.length) return false;
    const at = ui.vertex && ui.vertex.id === shape.id ? usable.indexOf(ui.vertex.index) : -1;
    const index = usable[at < 0 ? (direction > 0 ? 0 : usable.length - 1) : (at + direction + usable.length) % usable.length];
    ui.vertex = { id: shape.id, index };
    renderShapes();
    announce(shape.kind === "keypoints" ? `${pointName(shape, index)}, ${VISIBILITY_NAMES[points[index][2]]}` : `Point ${index + 1} of ${points.length}`);
    return true;
  }

  // ---- keypoints --------------------------------------------------------------------------
  let lastKeypointAt = -1e9;

  /** Start a new set of keypoints for the active class, or explain why that is not possible. */
  function beginKeypoints() {
    if (ui.kp) return ui.kp;
    const cls = classById(activeClassId());
    if (!cls) { needClass(); return null; }
    if (!cls.skeleton) {
      toast(`Class “${cls.name}” has no keypoints yet. Edit the class and list its points.`, { error: true, actionLabel: "Edit class", onAction: () => editClass(cls) });
      return null;
    }
    if (!canAdd()) return null;
    ui.kp = { classId: cls.id, points: cls.skeleton.names.map(() => [0, 0, NOT_LABELLED]), next: 0 };
    return ui.kp;
  }

  function placeKeypointAt(p, hidden) {
    const kp = beginKeypoints();
    if (!kp) return;
    const point = [clamp(p.x, 0, width), clamp(p.y, 0, height)];
    const previous = kp.points[kp.next - 1];
    // 2nd half of an accidental double-click: same spot, moments later
    if (previous && previous[2] && performance.now() - lastKeypointAt < DOUBLE_CLICK_GUARD_MS && screenGap(point, previous) < MIN_POINT_GAP_PX) return;
    lastKeypointAt = performance.now();
    kp.points[kp.next] = [point[0], point[1], hidden ? HIDDEN : VISIBLE];
    kp.next += 1;
    afterKeypointStep();
  }

  function skipKeypoint() {
    const kp = beginKeypoints();
    if (!kp) return;
    kp.points[kp.next] = [0, 0, NOT_LABELLED];
    kp.next += 1;
    afterKeypointStep();
  }

  function afterKeypointStep() {
    const kp = ui.kp;
    if (kp.next >= kp.points.length) { finishKeypoints(); return; }
    renderShapes();
    const cls = classById(kp.classId);
    announce(`Next: ${cls?.skeleton?.names?.[kp.next] ?? `point ${kp.next + 1}`}, ${kp.next + 1} of ${kp.points.length}`);
  }

  function removeLastKeypoint() {
    const kp = ui.kp;
    if (!kp) return;
    if (kp.next > 0) { kp.next -= 1; kp.points[kp.next] = [0, 0, NOT_LABELLED]; }
    if (kp.next === 0) ui.kp = null;
    renderShapes();
  }

  function cancelKeypoints() {
    ui.kp = null;
    renderShapes();
    announce("Keypoints cancelled");
  }

  function finishKeypoints() {
    const kp = ui.kp;
    if (!kp) return;
    const placed = kp.points.filter((point) => point[2] !== NOT_LABELLED).length;
    if (!placed) { toast("Place at least one point first.", { error: true }); return; }
    if (!canAdd()) { ui.kp = null; renderShapes(); return; }
    const id = newId();
    ui.kp = null;
    commit(addKeypoints(history.present, id, kp.classId, kp.points));
    ui.selection = new Set([id]);
    ui.vertex = null;
    renderAll();
    announce(`Keypoints added, ${placed} of ${kp.points.length} points placed`);
  }

  /** Keyboard-only: drop a whole pose in the middle of the view, then pick points with [ ] and move them with the arrows. */
  function keypointsAtCentre() {
    const cls = classById(activeClassId());
    if (!cls) { needClass(); return; }
    if (!cls.skeleton) { toast(`Class “${cls.name}” has no keypoints yet. Edit the class and list its points.`, { error: true }); return; }
    if (!canAdd()) return;
    const r = stageRect();
    const visible = visibleRect(ui.view, r.width, r.height, width, height);
    const points = defaultKeypoints(cls.skeleton.names.length, visible.x + visible.w / 2, visible.y + visible.h / 2, visible.w, visible.h, width, height);
    const id = newId();
    commit(addKeypoints(history.present, id, cls.id, points));
    ui.selection = new Set([id]);
    renderAll();
    announce("Keypoints added. Press ] to pick a point, then use the arrow keys to move it. O changes whether it is visible, hidden or not labelled.");
  }

  /** Make point `index` of a set not labelled (refused when it is the last labelled point). */
  function clearKeypoint(id, index) {
    const next = setKeypointVisibility(history.present, id, index, NOT_LABELLED);
    if (next === history.present) { toast("A set of keypoints needs at least one labelled point. Delete the whole set instead.", { error: true }); return false; }
    commit(next);
    ui.vertex = null;
    renderAll();
    return true;
  }

  /** Change one point's visibility: visible -> hidden -> not labelled -> visible. */
  function cycleKeypoint(id, index) {
    const shape = history.present.annotations.find((a) => a.id === id && a.kind === "keypoints");
    if (!shape || !shape.data.points[index]) return;
    const to = nextVisibility(shape.data.points[index][2]);
    if (to === NOT_LABELLED) { if (clearKeypoint(id, index)) announce(`${pointName(shape, index)} not labelled`); return; }
    const r = stageRect();
    const visible = visibleRect(ui.view, r.width, r.height, width, height);
    const bounds = keypointsBounds(shape.data.points);
    const fallback = bounds ? [bounds.minX + bounds.w / 2, bounds.minY + bounds.h / 2] : [visible.x + visible.w / 2, visible.y + visible.h / 2];
    commit(setKeypointVisibility(history.present, id, index, to, fallback));
    ui.vertex = { id, index };
    renderAll();
    announce(`${pointName(shape, index)} ${VISIBILITY_NAMES[to]}`);
  }

  function cycleCurrentKeypoint() {
    const shape = selectedPointShape();
    if (!shape || shape.kind !== "keypoints" || !ui.vertex) return false;
    cycleKeypoint(shape.id, ui.vertex.index);
    return true;
  }

  function deleteVertex(id, index) {
    if (history.present.annotations.find((a) => a.id === id)?.kind === "keypoints") { clearKeypoint(id, index); return; }
    const next = removeVertex(history.present, id, index);
    if (next === history.present) { toast("A polygon needs at least 3 points. Delete the whole polygon instead.", { error: true }); return; }
    if (!commitPolygonEdit(next, id)) return;
    const left = next.annotations.find((a) => a.id === id).data.points.length;
    ui.vertex = { id, index: Math.min(index, left - 1) };
    renderAll();
    announce(`Point removed, ${left} left`);
  }

  function insertVertexAfterCurrent() {
    const polygon = selectedPolygon();
    if (!polygon || !ui.vertex || ui.vertex.id !== polygon.id) return false;
    const points = polygon.data.points;
    const index = ui.vertex.index;
    if (index >= points.length) { ui.vertex = null; return false; }
    const [x, y] = midpoint(points[index], points[(index + 1) % points.length]);
    commit(insertVertex(history.present, polygon.id, index, x, y, width, height));
    ui.vertex = { id: polygon.id, index: index + 1 };
    renderAll();
    announce(`Point added, ${points.length + 1} points`);
    return true;
  }

  function nudgeVertex(dx, dy) {
    const shape = selectedPointShape();
    if (shape && shape.kind === "keypoints" && ui.vertex) {
      const point = shape.data.points[ui.vertex.index];
      if (!point || point[2] === NOT_LABELLED) { ui.vertex = null; return; }
      commit(placeKeypoint(history.present, shape.id, ui.vertex.index, point[0] + dx, point[1] + dy, point[2], width, height), { key: `kpnudge:${ui.vertex.index}` });
      return;
    }
    const polygon = selectedPolygon();
    if (!polygon || !ui.vertex) return;
    const point = polygon.data.points[ui.vertex.index];
    if (!point) { ui.vertex = null; return; }
    commitPolygonEdit(moveVertex(history.present, polygon.id, ui.vertex.index, point[0] + dx, point[1] + dy, width, height), polygon.id, { key: `vertexnudge:${ui.vertex.index}` });
  }

  function simplifySelected() {
    const polygon = selectedPolygon();
    if (!polygon) { toast("Select a polygon first."); return; }
    const { state, before, after } = simplifyAnnotation(history.present, polygon.id, limits.simplify_epsilon_px);
    if (after >= before) { toast("Nothing to simplify: every point matters at this tolerance."); return; }
    if (!commitPolygonEdit(state, polygon.id)) return;
    ui.vertex = null;
    renderAll();
    toast(`Reduced the polygon from ${before} to ${after} points`, { actionLabel: "Undo", onAction: undo });
  }

  /** A polygon with (almost) no area is refused by the server, so do not apply an edit that makes one. */
  function commitPolygonEdit(next, id, options = {}) {
    const polygon = next.annotations.find((a) => a.id === id && a.kind === "polygon");
    if (polygon && polygonArea(polygon.data.points) < limits.min_polygon_area_px) {
      ui.preview = null;
      toast("That would flatten the polygon, so the change was not applied.", { error: true });
      renderAll();
      return false;
    }
    return commit(next, options);
  }

  // The crossing test is O(n^2): remember the answer per points array (unchanged polygons keep their array).
  const crossingCache = new WeakMap();
  const crossingOf = (points) => {
    if (!crossingCache.has(points)) crossingCache.set(points, polygonSelfIntersects(points));
    return crossingCache.get(points);
  };

  function annotationLabel(a, i) {
    const kind = a.kind === "box" ? "Box" : a.kind === "polygon" ? "Polygon" : a.kind === "keypoints" ? "Keypoints" : a.kind;
    let detail = "";
    if (a.kind === "keypoints") {
      const placed = a.data.points.filter((point) => point[2] !== NOT_LABELLED).length;
      detail = ` · ${placed} of ${a.data.points.length} points`;
    }
    if (a.kind === "polygon") {
      const crossing = a.data.points.length <= 300 && crossingOf(a.data.points);
      detail = ` · ${a.data.points.length} points${crossing ? " · crosses itself" : ""}`;
    }
    return `${kind} ${i + 1} · ${classById(a.class_id)?.name ?? "?"}${detail}`;
  }

  async function repeatPrevious() {
    if (neighbours.previous === null) return;
    try {
      const previous = await api(`/api/images/${neighbours.previous}/annotations`);
      const { state, ids, skipped } = appendFromServer(history.present, previous, newId, new Set(classes.map((c) => c.id)), width, height);
      if (!ids.length) {
        toast(skipped ? `None of the previous image's ${plural(skipped, "annotation")} fit this image's size.` : "The previous image has no annotations to copy.", { error: Boolean(skipped) });
        return;
      }
      if (!canAdd(ids.length)) return;
      commit(state);
      ui.selection = new Set(ids);
      renderAll();
      const note = skipped ? `, skipped ${skipped} that do not fit this image's size` : "";
      toast(`Copied ${plural(ids.length, "annotation")} from the previous image${note}`, { actionLabel: "Undo", onAction: undo });
    } catch (error) {
      toast(error.message, { error: true });
    }
  }

  // ---- classes ----------------------------------------------------------------------------
  async function reloadClasses(kind) {
    if (kind === "deleted") {
      // Deleting a class can delete annotations on this image: reload everything from the server.
      await saver.flush();
      await loadAll();
      hideBanner();
      renderAll();
      return;
    }
    classes = await api(`/api/projects/${projectId}/classes`);
    ui.kp = null; // its skeleton may just have changed
    if (kind === "created" && ui.activeClass === null) ui.activeClass = classes[0]?.id ?? null;
    renderAll();
  }
  function addClass() { openClassDialog({ projectId, existing: null, onChanged: reloadClasses }); }
  function editClass(cls) { openClassDialog({ projectId, existing: cls, onChanged: reloadClasses }); }

  // ---- saving: recovery and conflicts -------------------------------------------------------
  function offerConflictChoice() {
    statusBanner = true;
    showBanner("This image was changed somewhere else, for example in another tab.", [
      { label: "Load the latest version", onClick: async () => { clearDraft(storage, imageId); await loadServerState(); hideBanner(); statusBanner = false; renderAll(); } },
      { label: "Keep my version", onClick: async () => {
        const latest = await api(`/api/images/${imageId}/annotations`);
        const mine = toPayload(history.present);
        saver.reset(latest.rev);
        saver.edit(mine);
        hideBanner();
      } },
    ]);
  }
  function offerRejectedChoice(detail) {
    statusBanner = true;
    showBanner(`The server did not accept these changes: ${detail.message}`, [
      { label: "Remove annotations that no longer fit", onClick: async () => {
        classes = await api(`/api/projects/${projectId}/classes`);
        commit(dropUnknownClasses(history.present, new Set(classes.map((c) => c.id))));
      } },
      { label: "Undo my last change", onClick: () => undo() },
      { label: "Load the latest version", onClick: async () => { clearDraft(storage, imageId); await loadServerState(); hideBanner(); statusBanner = false; renderAll(); } },
    ]);
  }
  function offerDraftRestore() {
    const draft = storage ? readDraft(storage, imageId) : null;
    if (!draft) return;
    if (JSON.stringify(draft.payload) === JSON.stringify(toPayload(history.present))) { clearDraft(storage, imageId); return; }
    showBanner("You have unsaved changes for this image from earlier on this computer.", [
      { label: "Restore them", onClick: () => {
        const restored = dropUnknownClasses(fromServer(draft.payload, newId), new Set(classes.map((c) => c.id)));
        commit(restored);
        hideBanner();
        announce("Unsaved changes restored");
      } },
      { label: "Discard them", onClick: () => { clearDraft(storage, imageId); hideBanner(); } },
    ]);
  }
  // Leaving the page (tab hidden, window closing) sends the pending edit through the SAME saver, so
  // there is never a second request carrying a stale revision (that produced a false conflict).
  const releaseKeys = () => { ui.space = false; stage.classList.remove("space-pan"); };
  const sendOnHide = () => { void saver?.flushNow({ keepalive: true }); };
  listen(document, "visibilitychange", () => { if (document.visibilityState === "hidden") { sendOnHide(); releaseKeys(); } });
  listen(window, "pagehide", sendOnHide);
  listen(window, "blur", releaseKeys); // a held Space must not stay "held" when the window loses focus

  // ---- navigation -------------------------------------------------------------------------
  async function go(id) {
    if (blockWhileDrawing()) return;
    if (id === null || id === undefined) { toast("There is no image in that direction."); return; }
    await saver.flush();
    if (saver.status === "error" || saver.status === "conflict") {
      toast("Your latest edits could not be saved yet. They are kept on this computer and offered again when you return.", { error: true });
    }
    navigate(`/projects/${projectId}/annotate/${id}`);
  }

  // ---- pointer ----------------------------------------------------------------------------
  listen(stage, "pointerdown", (event) => {
    if (event.button === 2) return;
    stage.focus({ preventScroll: true });
    const p = imagePoint(event);
    if (event.button === 1 || ui.tool === "pan" || ui.space) {
      ui.drag = { type: "pan", x: event.clientX, y: event.clientY };
      stage.setPointerCapture(event.pointerId);
      stage.classList.add("panning");
      event.preventDefault();
      return;
    }
    if (event.button !== 0) return;
    if (ui.tool === "polygon") {
      if (activeClassId() === null) {
        ui.drag = { type: "needclass" };
        stage.setPointerCapture(event.pointerId);
        return;
      }
      addPolygonPoint(p);
      return;
    }
    if (ui.tool === "keypoints") {
      if (activeClassId() === null) {
        ui.drag = { type: "needclass" };
        stage.setPointerCapture(event.pointerId);
        return;
      }
      placeKeypointAt(p, event.shiftKey);
      return;
    }
    if (ui.tool === "box") {
      if (activeClassId() === null) {
        // Do not open the dialog on press: the release would land on it and steal its focus.
        ui.drag = { type: "needclass" };
        stage.setPointerCapture(event.pointerId);
        return;
      }
      ui.drag = { type: "draw", x0: p.x, y0: p.y };
      ui.draft = boxFromPoints(p.x, p.y, p.x, p.y, width, height);
      stage.setPointerCapture(event.pointerId);
      return;
    }
    const kpNode = event.target.closest?.("[data-kp]");
    if (kpNode) {
      const id = kpNode.dataset.id;
      const index = Number(kpNode.dataset.kp);
      if (event.altKey) { clearKeypoint(id, index); return; } // Alt+click makes a point "not labelled"
      const shape = history.present.annotations.find((a) => a.id === id);
      ui.vertex = { id, index };
      ui.drag = { type: "kpoint", id, index, v: shape?.data.points[index]?.[2] ?? VISIBLE, start: history.present, moved: false };
      stage.setPointerCapture(event.pointerId);
      renderShapes();
      return;
    }
    const vertexNode = event.target.closest?.("[data-vertex]");
    const midNode = event.target.closest?.("[data-mid]");
    const handleNode = event.target.closest?.("[data-handle]");
    const shapeNode = event.target.closest?.("[data-id]");
    if (vertexNode) {
      const id = vertexNode.dataset.id;
      const index = Number(vertexNode.dataset.vertex);
      if (event.altKey) { deleteVertex(id, index); return; } // Alt+click removes a point
      ui.vertex = { id, index };
      ui.drag = { type: "vertex", id, index, start: history.present, moved: false };
      stage.setPointerCapture(event.pointerId);
      renderShapes();
      return;
    }
    if (midNode) {
      // Dragging an edge's midpoint inserts a new point there and moves it: one undo step for both.
      const id = midNode.dataset.id;
      const after = Number(midNode.dataset.mid);
      const inserted = insertVertex(history.present, id, after, p.x, p.y, width, height);
      ui.vertex = { id, index: after + 1 };
      ui.preview = inserted;
      ui.drag = { type: "vertex", id, index: after + 1, start: inserted, moved: true };
      stage.setPointerCapture(event.pointerId);
      renderShapes();
      return;
    }
    if (handleNode) {
      ui.drag = { type: "resize", id: handleNode.dataset.id, handle: handleNode.dataset.handle, start: history.present, moved: false };
      stage.setPointerCapture(event.pointerId);
    } else if (shapeNode) {
      const id = shapeNode.dataset.id;
      ui.vertex = null;
      if (event.shiftKey) { if (ui.selection.has(id)) ui.selection.delete(id); else ui.selection.add(id); }
      else if (!ui.selection.has(id)) ui.selection = new Set([id]);
      ui.drag = { type: "move", ids: [...ui.selection], start: history.present, x0: p.x, y0: p.y, sx0: p.sx, sy0: p.sy, moved: false };
      stage.setPointerCapture(event.pointerId);
      renderAll();
    } else if (!event.shiftKey && (ui.selection.size || ui.vertex)) {
      ui.selection.clear();
      ui.vertex = null;
      renderAll();
    }
  });
  listen(stage, "pointermove", (event) => {
    const p = imagePoint(event);
    updateHud(p);
    if (ui.tool === "polygon" && ui.poly && !ui.drag) { // the rubber band follows the pointer
      ui.poly.cursor = [Math.min(Math.max(p.x, 0), width), Math.min(Math.max(p.y, 0), height)];
      renderPolygonDraft();
      return;
    }
    const drag = ui.drag;
    if (!drag) return;
    if (drag.type === "pan") {
      ui.view = panBy(ui.view, event.clientX - drag.x, event.clientY - drag.y);
      drag.x = event.clientX; drag.y = event.clientY;
      ui.fitted = false;
      viewport.style.transform = `translate(${ui.view.tx}px, ${ui.view.ty}px) scale(${ui.view.scale})`;
    } else if (drag.type === "draw") {
      ui.draft = boxFromPoints(drag.x0, drag.y0, p.x, p.y, width, height);
      renderShapes();
    } else if (drag.type === "move") {
      if (!drag.moved && Math.hypot(p.sx - drag.sx0, p.sy - drag.sy0) < DRAG_START_PX) return;
      drag.moved = true;
      ui.preview = moveAnnotations(drag.start, drag.ids, p.x - drag.x0, p.y - drag.y0, width, height);
      updateGeometry();
    } else if (drag.type === "resize") {
      drag.moved = true;
      ui.preview = resizeAnnotationTo(drag.start, drag.id, drag.handle, p.x, p.y, width, height, minBox());
      updateGeometry();
    } else if (drag.type === "kpoint") {
      drag.moved = true;
      ui.preview = placeKeypoint(drag.start, drag.id, drag.index, p.x, p.y, drag.v, width, height);
      updateGeometry();
    } else if (drag.type === "vertex") {
      drag.moved = true;
      ui.preview = moveVertex(drag.start, drag.id, drag.index, p.x, p.y, width, height);
      updateGeometry();
    }
  });
  const finishDrag = (event, cancelled) => {
    const drag = ui.drag;
    if (!drag) return;
    ui.drag = null;
    stage.classList.remove("panning");
    try { stage.releasePointerCapture(event.pointerId); } catch { /* already released */ }
    if (drag.type === "pan") { applyView(); return; }
    if (drag.type === "needclass") { if (!cancelled) needClass(); return; }
    if (drag.type === "draw") {
      const box = ui.draft;
      ui.draft = null;
      const bigEnough = box && box.w * ui.view.scale >= MIN_DRAW_PX && box.h * ui.view.scale >= MIN_DRAW_PX && box.w >= minBox() && box.h >= minBox();
      if (!cancelled && bigEnough && canAdd()) {
        const id = newId();
        commit(addBox(history.present, id, activeClassId(), box));
        ui.selection = new Set([id]);
        renderAll();
        announce("Box added");
      } else {
        renderShapes();
      }
      return;
    }
    if (!cancelled && drag.moved && ui.preview) {
      if (drag.type === "vertex") commitPolygonEdit(ui.preview, drag.id);
      else commit(ui.preview);
    } else {
      ui.preview = null;
      renderShapes();
    }
  };
  listen(stage, "pointerup", (event) => finishDrag(event, false));
  listen(stage, "dblclick", () => { if (ui.tool === "polygon" && ui.poly && ui.poly.points.length >= 3) finishPolygon(); });
  listen(stage, "pointercancel", (event) => finishDrag(event, true));
  listen(stage, "lostpointercapture", (event) => { if (ui.drag) finishDrag(event, true); });
  listen(stage, "wheel", (event) => {
    event.preventDefault();
    const { sx, sy } = stagePoint(event);
    ui.view = zoomAt(ui.view, Math.exp(-event.deltaY * (event.ctrlKey ? 0.01 : 0.0015)), sx, sy);
    ui.fitted = false;
    if (ui.poly) { const under = screenToImage(ui.view, sx, sy); ui.poly.cursor = [under.x, under.y]; } // no stale rubber band
    applyView();
  }, { passive: false });

  // ---- keyboard ---------------------------------------------------------------------------
  const DIGITS = { Digit1: 1, Digit2: 2, Digit3: 3, Digit4: 4, Digit5: 5, Digit6: 6, Digit7: 7, Digit8: 8, Digit9: 9, Numpad1: 1, Numpad2: 2, Numpad3: 3, Numpad4: 4, Numpad5: 5, Numpad6: 6, Numpad7: 7, Numpad8: 8, Numpad9: 9 };
  listen(document, "keydown", (event) => {
    if (document.querySelector("dialog[open]") || isTyping(event.target)) return;
    const key = event.key;
    const lower = key.toLowerCase();
    const ctrl = event.ctrlKey || event.metaKey;
    const onStage = event.target === stage || event.target === document.body || stage.contains(event.target);

    if (ctrl) {
      if (lower === "z") { event.preventDefault(); if (event.shiftKey) redo(); else undo(); }
      else if (lower === "y") { event.preventDefault(); redo(); }
      else if (lower === "d") { event.preventDefault(); duplicateSelection(); }
      else if (lower === "a" && onStage) { event.preventDefault(); ui.selection = new Set(history.present.annotations.map((a) => a.id)); renderAll(); }
      else if (lower === "s") { event.preventDefault(); void saver.flushNow(); toast("Changes are saved automatically."); } // not the browser's Save dialog
      return; // Ctrl+K and friends belong to the app shell
    }
    if (event.altKey && !key.startsWith("Arrow")) return; // Alt+letter is the browser's, not ours
    if (event.code in DIGITS && !event.altKey) {
      const target = classes[DIGITS[event.code] - 1];
      if (!target) return;
      event.preventDefault();
      if (event.shiftKey) toggleLabel(target.id); else chooseClass(target.id);
      return;
    }
    if (key === " " && onStage) { event.preventDefault(); ui.space = true; stage.classList.add("space-pan"); return; }
    if (lower === "v") setTool("select");
    else if (lower === "b") setTool("box");
    else if (lower === "p") setTool("polygon");
    else if (lower === "k") setTool("keypoints");
    else if (lower === "h") setTool("pan");
    else if (key === "0") fit();
    else if (key === "+" || key === "=") zoomStep(1.25);
    else if (key === "-") zoomStep(0.8);
    else if (lower === "a" && !event.shiftKey) go(neighbours.previous);
    else if (lower === "d" && !event.shiftKey) go(neighbours.next);
    else if (lower === "n") go(neighbours.next_unlabelled);
    else if (lower === "e") toggleEmpty();
    else if ((key === "Delete" || key === "Backspace") && onStage) {
      event.preventDefault();
      if (ui.poly) removeLastPolygonPoint();
      else if (ui.kp) removeLastKeypoint();
      else if (ui.vertex) deleteVertex(ui.vertex.id, ui.vertex.index);
      else deleteSelection();
    } else if (key === "Escape") {
      if (ui.drag) { event.preventDefault(); finishDrag({ pointerId: -1 }, true); }
      else if (ui.poly) { event.preventDefault(); ui.poly = null; renderShapes(); announce("Polygon cancelled"); }
      else if (ui.kp) { event.preventDefault(); cancelKeypoints(); }
      else if (ui.vertex) { event.preventDefault(); ui.vertex = null; renderShapes(); }
      else if (ui.selection.size) { event.preventDefault(); ui.selection.clear(); renderAll(); }
    } else if (key === "Enter" && onStage && ui.tool === "polygon") { event.preventDefault(); if (ui.poly) finishPolygon(); else polygonAtCentre(); }
    else if (key === "Enter" && onStage && ui.tool === "keypoints") { event.preventDefault(); if (ui.kp) finishKeypoints(); else keypointsAtCentre(); }
    else if (lower === "x" && onStage && ui.tool === "keypoints") { event.preventDefault(); skipKeypoint(); }
    else if (lower === "o" && onStage) { if (cycleCurrentKeypoint()) event.preventDefault(); }
    else if (key === "Enter" && onStage && ui.tool === "box") { event.preventDefault(); boxAtCentre(); }
    else if ((key === "[" || key === "]") && onStage) { if (stepVertex(key === "]" ? 1 : -1)) event.preventDefault(); }
    else if (lower === "i" && onStage) { if (insertVertexAfterCurrent()) event.preventDefault(); }
    else if (key === "Tab" && event.target === stage) {
      const only = ui.selection.size === 1 ? [...ui.selection][0] : null;
      const next = cycle(history.present, only, event.shiftKey ? -1 : 1);
      if (next !== null) { event.preventDefault(); ui.selection = new Set([next]); renderAll(); announce(`${annotationLabel(history.present.annotations.find((a) => a.id === next), history.present.annotations.findIndex((a) => a.id === next))} selected`); }
    } else if (onStage && key.startsWith("Arrow") && ui.selection.size) {
      event.preventDefault();
      const step = event.shiftKey ? NUDGE_BIG : NUDGE;
      const dx = key === "ArrowRight" ? step : key === "ArrowLeft" ? -step : 0;
      const dy = key === "ArrowDown" ? step : key === "ArrowUp" ? -step : 0;
      if (ui.vertex && !event.altKey) nudgeVertex(dx, dy); // a selected point moves alone
      else nudge(dx, dy, event.altKey);
    }
  });
  listen(document, "keyup", (event) => {
    if (event.key === " ") { ui.space = false; stage.classList.remove("space-pan"); }
  });

  // ---- start ------------------------------------------------------------------------------
  ui.activeClass = classes[0]?.id ?? null;
  setToolbar({
    title: image.original_name,
    actions: [
      el("a", { class: "btn btn-quiet", href: `#/projects/${projectId}` }, icon("back"), "Gallery"),
      el("button", { class: "btn btn-icon", type: "button", "aria-label": "Previous image (A)", title: "Previous image (A)", disabled: neighbours.previous === null, onclick: () => go(neighbours.previous) }, icon("back")),
      el("button", { class: "btn btn-icon", type: "button", "aria-label": "Next image (D)", title: "Next image (D)", disabled: neighbours.next === null, onclick: () => go(neighbours.next) }, icon("next")),
      el("button", { class: "btn", type: "button", disabled: neighbours.next_unlabelled === null, onclick: () => go(neighbours.next_unlabelled) }, "Next unlabelled ", el("kbd", { text: "N" })),
      statusChip,
    ],
    commands: [
      { label: "Next unlabelled image", hint: "N", run: () => go(neighbours.next_unlabelled) },
      { label: "Mark image as having no objects", hint: "E", run: toggleEmpty },
      { label: "Fit image to window", hint: "0", run: fit },
      { label: "Undo", hint: "Ctrl Z", run: undo },
      { label: "Redo", hint: "Ctrl Shift Z", run: redo },
      { label: "Add a class", hint: "", run: addClass },
      { label: "Simplify selected polygon", hint: "", run: simplifySelected },
      { label: "Repeat previous image's annotations", hint: "", run: repeatPrevious },
    ],
  });
  fit();
  renderAll();
  loadFilmstrip();
  offerDraftRestore();
  stage.focus({ preventScroll: true });

  return () => {
    for (const undoListener of cleanups) undoListener();
    if (saver) {
      const done = saver;
      done.flush().finally(() => done.dispose()); // finish saving in the background after leaving
    }
  };
}
