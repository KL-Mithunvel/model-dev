// Project gallery: thumbnails, filters, selection, inspector (split + tags), import, auto-split.
import { api, watchJob } from "../api.js";
import { limits } from "../limits.js";
import { openClassManager } from "../classes.js";
import { openExportDialog, openLabelImportDialog } from "../labels.js";
import { el, formatBytes, formatDate, icon, isTyping, openDialog, plural, toast } from "../ui.js";

const SPLITS = ["train", "val", "test"];
const SPLIT_LABEL = { train: "Train", val: "Validation", test: "Test" };

export async function mount(container, { setToolbar, navigate, projectId }) {
  const state = {
    project: null,
    items: [],
    total: 0,
    filters: { split: "", tag: "", q: "", labelled: "", class_id: "" },
    classes: [],
    stats: null,
    selection: new Set(),
    anchor: null,
    focusIndex: 0,
    tags: [],
    loading: false,
    token: 0,
    pageSize: limits.page_size,
  };

  const layout = el("div", { class: "gallery no-inspector" });
  const filtersBar = el("div", { class: "filters" });
  const scroll = el("div", { class: "gallery-scroll" });
  const grid = el("div", { class: "grid", role: "group", "aria-label": "Images" });
  const more = el("div", { class: "load-more" });
  const sentinel = el("div", { "aria-hidden": "true" });
  const inspector = el("aside", { class: "inspector", "aria-label": "Image details", hidden: true });
  scroll.append(grid, more, sentinel);
  layout.append(el("div", { class: "gallery-main" }, filtersBar, scroll), inspector);
  container.replaceChildren(layout);

  // ---- data loading ----------------------------------------------------------------------
  async function loadProject() {
    state.project = await api(`/api/projects/${projectId}`);
    state.tags = await api(`/api/projects/${projectId}/tags`);
    state.classes = await api(`/api/projects/${projectId}/classes`);
    state.stats = await api(`/api/projects/${projectId}/annotation-stats`);
  }

  function query(offset) {
    const params = new URLSearchParams({ offset: String(offset), limit: String(state.pageSize) });
    for (const [key, value] of Object.entries(state.filters)) if (value) params.set(key, value);
    return `/api/projects/${projectId}/images?${params}`;
  }

  async function loadPage(reset) {
    if (state.loading && !reset) return;
    const token = ++state.token;
    state.loading = true;
    if (reset) {
      state.items = [];
      state.selection.clear();
      state.anchor = null;
      state.focusIndex = 0;
      grid.replaceChildren(el("div", { class: "state-box", text: "Loading images…" }));
    }
    renderMore();
    const firstNew = state.items.length;
    try {
      const page = await api(query(state.items.length));
      if (token !== state.token) return; // a newer request superseded this one
      state.pageSize = page.limit;
      state.total = page.total;
      state.items.push(...page.items);
    } catch (error) {
      if (token !== state.token) return;
      state.loading = false;
      if (!reset) {
        renderMore();
        toast(error.message, { error: true });
        return;
      }
      grid.replaceChildren(
        el("div", { class: "state-box", role: "alert" }, el("p", { text: error.message }), el("button", { class: "btn", type: "button", text: "Try again", onclick: () => loadPage(true) })),
      );
      return;
    }
    state.loading = false;
    if (reset) {
      renderAll();
    } else {
      // Append only the new tiles: rebuilding the grid would destroy the focused tile and
      // throw keyboard users back to the top of the page.
      grid.append(...state.items.slice(firstNew).map((item, offset) => renderTile(item, firstNew + offset)));
      renderMore();
      updateSummary();
    }
  }

  // ---- rendering -------------------------------------------------------------------------
  function selectedItems() {
    return state.items.filter((item) => state.selection.has(item.id));
  }

  let clearButton = null;
  function syncClear() {
    if (clearButton) clearButton.hidden = !Object.values(state.filters).some(Boolean);
  }

  function renderFilters() {
    const splitSelect = el("select", { class: "input", id: "f-split", "aria-label": "Filter by split", onchange: (e) => { state.filters.split = e.target.value; syncClear(); loadPage(true); } },
      el("option", { value: "", text: "All splits" }),
      ...[...SPLITS, "unassigned"].map((s) => el("option", { value: s, text: s === "unassigned" ? "No split" : SPLIT_LABEL[s], selected: state.filters.split === s })),
    );
    const tagSelect = el("select", { class: "input", id: "f-tag", "aria-label": "Filter by tag", onchange: (e) => { state.filters.tag = e.target.value; syncClear(); loadPage(true); } },
      el("option", { value: "", text: "All tags" }),
      ...state.tags.map((t) => el("option", { value: t.tag, text: `${t.tag} (${t.count})`, selected: state.filters.tag === t.tag })),
    );
    const labelledSelect = el("select", { class: "input", id: "f-labelled", "aria-label": "Filter by labelling", onchange: (e) => { state.filters.labelled = e.target.value; syncClear(); loadPage(true); } },
      el("option", { value: "", text: "Labelled or not" }),
      el("option", { value: "true", text: "Labelled", selected: state.filters.labelled === "true" }),
      el("option", { value: "false", text: "Not labelled yet", selected: state.filters.labelled === "false" }),
    );
    const classSelect = el("select", { class: "input", id: "f-class", "aria-label": "Filter by class", onchange: (e) => { state.filters.class_id = e.target.value; syncClear(); loadPage(true); } },
      el("option", { value: "", text: "All classes" }),
      ...state.classes.map((c) => el("option", { value: String(c.id), text: c.name, selected: state.filters.class_id === String(c.id) })),
    );
    let timer = null;
    const search = el("input", {
      class: "input search", id: "f-search", type: "search", placeholder: "Search file names", "aria-label": "Search file names", value: state.filters.q,
      oninput: (e) => {
        clearTimeout(timer);
        timer = setTimeout(() => { state.filters.q = e.target.value.trim(); syncClear(); loadPage(true); }, 250);
      },
    });
    // One persistent button whose visibility follows the filters (rebuilding the bar on every
    // change would drop keyboard focus from the control the user is using).
    clearButton = el("button", { class: "btn btn-quiet", type: "button", text: "Clear filters", onclick: clearFilters });
    syncClear();
    filtersBar.replaceChildren(
      splitSelect, tagSelect, labelledSelect, classSelect, search,
      clearButton,
      el("span", { class: "muted num", id: "summary", role: "status" }),
    );
  }

  function clearFilters() {
    state.filters = { split: "", tag: "", q: "", labelled: "", class_id: "" };
    renderFilters();
    loadPage(true);
  }

  function updateSummary() {
    const node = document.getElementById("summary");
    if (!node) return;
    const sel = state.selection.size ? ` · ${state.selection.size.toLocaleString()} selected` : "";
    const progress = state.stats ? ` · ${state.stats.labelled.toLocaleString()} of ${state.stats.images.toLocaleString()} labelled` : "";
    node.textContent = `${state.items.length.toLocaleString()} of ${state.total.toLocaleString()} shown${sel}${progress}`;
  }

  function tileLabel(item) {
    const parts = [item.original_name, item.split ? `${SPLIT_LABEL[item.split]} split` : "no split"];
    if (item.tags.length) parts.push(`tags: ${item.tags.join(", ")}`);
    if (item.annotation_count) parts.push(`${item.annotation_count} annotation${item.annotation_count === 1 ? "" : "s"}`);
    else if (item.marked_empty) parts.push("marked as no objects");
    const label = state.classes.find((c) => c.id === item.label_class_id);
    if (label) parts.push(`labelled ${label.name}`);
    return parts.join(", ");
  }

  function annotationBadge(item) {
    const label = state.classes.find((c) => c.id === item.label_class_id);
    const text = item.annotation_count ? String(item.annotation_count) : item.marked_empty ? "empty" : label ? label.name : null;
    return text === null ? null : el("span", { class: "badge badge-right" }, icon("box"), text);
  }

  function renderTile(item, index) {
    const selected = state.selection.has(item.id);
    const tile = el(
      "button",
      {
        class: "tile", type: "button", "aria-pressed": String(selected), "aria-label": tileLabel(item),
        tabindex: index === state.focusIndex ? "0" : "-1", "data-id": String(item.id), "data-index": String(index),
      },
      el("img", { src: item.thumb_url, alt: "", loading: "lazy", draggable: "false" }),
      el("span", { class: "name", text: item.original_name }),
      item.split ? el("span", { class: "badge" }, el("i", { class: `dot ${item.split}` }), SPLIT_LABEL[item.split]) : null,
      annotationBadge(item),
    );
    return tile;
  }

  function renderGrid() {
    if (!state.items.length) {
      const filtered = Object.values(state.filters).some(Boolean);
      grid.replaceChildren(
        filtered
          ? el("div", { class: "empty" }, el("h3", { text: "No images match" }), el("p", { text: "Try a different search or clear the filters." }), el("button", { class: "btn", type: "button", text: "Clear filters", onclick: clearFilters }))
          : el("div", { class: "empty" }, icon("upload"), el("h3", { text: "Add your first images" }), el("p", { text: "Choose a folder or a .zip file. Images are copied into this project; nothing leaves your computer." }), el("button", { class: "btn btn-primary", type: "button", onclick: openImport }, icon("upload"), "Import images")),
      );
      return;
    }
    grid.replaceChildren(...state.items.map(renderTile));
  }

  function renderMore() {
    more.replaceChildren();
    if (state.items.length < state.total) {
      more.append(el("button", { class: "btn", type: "button", disabled: state.loading, text: state.loading ? "Loading…" : `Load more (${(state.total - state.items.length).toLocaleString()} left)`, onclick: () => loadPage(false) }));
    }
  }

  function renderAll() {
    renderGrid();
    renderMore();
    renderInspector();
    updateSummary();
  }

  function refreshSelectionUi() {
    for (const tile of grid.querySelectorAll(".tile")) {
      tile.setAttribute("aria-pressed", String(state.selection.has(Number(tile.dataset.id))));
    }
    renderInspector();
    updateSummary();
  }

  // ---- inspector -------------------------------------------------------------------------
  async function applySplit(items, split) {
    const ids = items.map((i) => i.id);
    const before = items.map((i) => [i.id, i.split]);
    try {
      await api(`/api/projects/${projectId}/split`, { method: "PUT", body: { image_ids: ids, split } });
    } catch (error) {
      toast(error.message, { error: true });
      return;
    }
    for (const item of items) item.split = split;
    await refreshProjectCounts();
    refreshTiles({ keepInspector: true });
    toast(split ? `Set ${plural(ids.length, "image")} to ${SPLIT_LABEL[split]}` : `Cleared the split on ${plural(ids.length, "image")}`, {
      actionLabel: "Undo",
      onAction: () => restoreSplits(before),
    });
  }

  async function restoreSplits(before) {
    const groups = new Map();
    for (const [id, split] of before) groups.set(split, [...(groups.get(split) || []), id]);
    try {
      for (const [split, ids] of groups) {
        await api(`/api/projects/${projectId}/split`, { method: "PUT", body: { image_ids: ids, split } });
      }
    } catch (error) {
      toast(error.message, { error: true });
    }
    await loadPage(true);
  }

  async function refreshProjectCounts() {
    state.project = await api(`/api/projects/${projectId}`);
  }

  // Re-render tiles in place. Keeps keyboard focus on the same tile; with keepInspector the
  // inspector is not rebuilt (that would drop focus from the button that was just pressed).
  function refreshTiles({ keepInspector = false } = {}) {
    const focusedIndex = document.activeElement?.closest?.(".tile")?.dataset.index;
    for (const tile of grid.querySelectorAll(".tile")) {
      const item = state.items[Number(tile.dataset.index)];
      if (!item) continue;
      tile.replaceWith(renderTile(item, Number(tile.dataset.index)));
    }
    if (focusedIndex !== undefined) {
      grid.querySelector(`.tile[data-index="${focusedIndex}"]`)?.focus();
    }
    if (keepInspector) syncSplitButtons();
    else renderInspector();
  }

  function syncSplitButtons() {
    const current = new Set(selectedItems().map((i) => i.split || ""));
    for (const button of inspector.querySelectorAll(".seg button")) {
      button.setAttribute("aria-pressed", String(current.size === 1 && current.has(button.dataset.value)));
    }
  }

  function splitControl(items) {
    const current = new Set(items.map((i) => i.split || ""));
    const group = el("div", { class: "seg", role: "group", "aria-label": "Split" });
    for (const [value, label] of [["train", "Train"], ["val", "Val"], ["test", "Test"], ["", "None"]]) {
      group.append(
        el("button", { type: "button", text: label, "data-value": value, "aria-pressed": String(current.size === 1 && current.has(value)), onclick: () => applySplit(items, value || null) }),
      );
    }
    return group;
  }

  function tagEditor(item) {
    const box = el("div", { class: "tag-box" });
    const input = el("input", { type: "text", "aria-label": "Add a tag", placeholder: item.tags.length ? "" : "Add a tag…", maxlength: String(limits.tag_max_length), list: "tag-suggestions" });
    const suggestions = el("datalist", { id: "tag-suggestions" }, ...state.tags.map((t) => el("option", { value: t.tag })));
    const save = async (tags) => {
      try {
        const result = await api(`/api/images/${item.id}/tags`, { method: "PUT", body: { tags } });
        item.tags = result.tags;
        state.tags = await api(`/api/projects/${projectId}/tags`);
        if (state.filters.tag && !state.tags.some((t) => t.tag === state.filters.tag)) {
          // The tag being filtered on no longer exists anywhere: drop the filter, don't leave a
          // dropdown that says "All tags" while the grid is still filtered.
          state.filters.tag = "";
          renderFilters();
          await loadPage(true);
          return;
        }
        refreshTiles();
        renderFilters();
        document.querySelector(".inspector .tag-box input")?.focus();
      } catch (error) {
        toast(error.message, { error: true });
      }
    };
    for (const tag of item.tags) {
      box.append(el("span", { class: "chip" }, tag, el("button", { type: "button", "aria-label": `Remove tag ${tag}`, onclick: () => save(item.tags.filter((t) => t !== tag)) }, "×")));
    }
    input.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === ",") && input.value.trim()) {
        event.preventDefault();
        save([...item.tags, input.value.trim()]);
      } else if (event.key === "Backspace" && !input.value && item.tags.length) {
        save(item.tags.slice(0, -1));
      }
    });
    box.append(input, suggestions);
    return box;
  }

  function renderInspector() {
    const chosen = selectedItems();
    layout.classList.toggle("no-inspector", chosen.length === 0);
    inspector.hidden = chosen.length === 0;
    if (!chosen.length) return;
    if (chosen.length === 1) {
      const item = chosen[0];
      inspector.replaceChildren(
        // width/height reserve the preview's space before it loads, so the controls below it do not jump
        el("img", { src: item.file_url, alt: `Preview of ${item.original_name}`, width: String(item.width), height: String(item.height) }),
        el("h3", { text: item.original_name }),
        el("button", { class: "btn btn-primary", type: "button", onclick: () => navigate(`/projects/${projectId}/annotate/${item.id}`) }, icon("box"), "Annotate this image"),
        el("dl", { class: "kv num" },
          el("dt", { text: "Size" }), el("dd", { text: `${item.width} × ${item.height} px` }),
          el("dt", { text: "File" }), el("dd", { text: formatBytes(item.bytes) }),
          el("dt", { text: "Added" }), el("dd", { text: formatDate(item.created_at) })),
        el("div", { class: "field" }, el("label", { text: "Split" }), splitControl([item])),
        el("div", { class: "field" }, el("label", { text: "Tags" }), tagEditor(item), el("span", { class: "hint", text: "Press Enter to add a tag." })),
      );
    } else {
      inspector.replaceChildren(
        el("h3", { text: `${plural(chosen.length, "image")} selected` }),
        el("div", { class: "field" }, el("label", { text: "Set split for all" }), splitControl(chosen)),
        el("button", { class: "btn", type: "button", text: "Clear selection", onclick: clearSelection }),
      );
    }
  }

  // ---- selection and keyboard ------------------------------------------------------------
  function clearSelection() {
    state.selection.clear();
    refreshSelectionUi();
  }

  function select(index, event) {
    const item = state.items[index];
    if (!item) return;
    if (event.shiftKey && state.anchor !== null) {
      const [from, to] = [Math.min(state.anchor, index), Math.max(state.anchor, index)];
      if (!(event.ctrlKey || event.metaKey)) state.selection.clear();
      for (let i = from; i <= to; i++) state.selection.add(state.items[i].id);
    } else if (event.ctrlKey || event.metaKey || event.toggle) {
      if (state.selection.has(item.id)) state.selection.delete(item.id);
      else state.selection.add(item.id);
      state.anchor = index;
    } else {
      state.selection = new Set([item.id]);
      state.anchor = index;
    }
    refreshSelectionUi();
  }

  function focusTile(index) {
    const clamped = Math.max(0, Math.min(index, state.items.length - 1));
    const tiles = grid.querySelectorAll(".tile");
    tiles[state.focusIndex]?.setAttribute("tabindex", "-1");
    state.focusIndex = clamped;
    const tile = tiles[clamped];
    if (tile) {
      tile.setAttribute("tabindex", "0");
      tile.focus();
    }
    if (clamped >= state.items.length - 1 && state.items.length < state.total) loadPage(false);
  }

  function columns() {
    const tiles = grid.querySelectorAll(".tile");
    if (!tiles.length) return 1;
    const top = tiles[0].offsetTop;
    let count = 0;
    for (const tile of tiles) {
      if (tile.offsetTop !== top) break;
      count++;
    }
    return Math.max(1, count);
  }

  grid.addEventListener("dblclick", (event) => {
    const tile = event.target.closest(".tile");
    if (tile) navigate(`/projects/${projectId}/annotate/${tile.dataset.id}`);
  });
  grid.addEventListener("click", (event) => {
    const tile = event.target.closest(".tile");
    if (!tile) return;
    for (const other of grid.querySelectorAll('.tile[tabindex="0"]')) other.setAttribute("tabindex", "-1");
    tile.setAttribute("tabindex", "0"); // exactly one tile is in the tab order
    state.focusIndex = Number(tile.dataset.index);
    select(state.focusIndex, event);
  });
  // A <button> fires click on Space keyup in some browsers; we already handled Space on keydown.
  grid.addEventListener("keyup", (event) => {
    if (event.key === " " && event.target.closest(".tile")) event.preventDefault();
  });
  grid.addEventListener("keydown", (event) => {
    const tile = event.target.closest(".tile");
    if (!tile) return;
    const index = Number(tile.dataset.index);
    const moves = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: columns(), ArrowUp: -columns() };
    if (event.key in moves) {
      event.preventDefault();
      focusTile(index + moves[event.key]);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusTile(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusTile(state.items.length - 1);
    } else if (event.key === " ") {
      event.preventDefault();
      select(index, { toggle: true });
    }
  });

  function onKey(event) {
    if (document.querySelector("dialog[open]") || isTyping(event.target)) return;
    if (event.key === "Escape" && state.selection.size) {
      clearSelection();
    } else if (event.key === "/") {
      event.preventDefault();
      document.getElementById("f-search")?.focus();
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      event.preventDefault();
      selectAllLoaded();
    }
  }
  document.addEventListener("keydown", onKey);

  function selectAllLoaded() {
    state.selection = new Set(state.items.map((i) => i.id));
    refreshSelectionUi();
  }

  const observer = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting) && state.items.length && state.items.length < state.total) loadPage(false);
  }, { root: scroll, rootMargin: "400px" });
  observer.observe(sentinel);

  // ---- import ----------------------------------------------------------------------------
  function openExport() { openExportDialog({ projectId }); }
  function openLabelImport() { openLabelImportDialog({ projectId, onDone: () => loadPage(true) }); }

  function openImport() {
    const body = el("div", { class: "stack" });
    const pathInput = el("input", { class: "input", id: "import-path", type: "text", autocomplete: "off", placeholder: String.raw`C:\Users\me\Pictures\photos   or   D:\data\photos.zip` });
    const problem = el("p", { class: "error-text", role: "alert" });
    let handle;
    let starting = false; // a double click or Enter+click must not start two imports
    const start = async () => {
      if (starting) return;
      starting = true;
      problem.textContent = "";
      let job;
      try {
        job = await api(`/api/projects/${projectId}/imports`, { method: "POST", body: { path: pathInput.value.trim() } });
      } catch (error) {
        problem.textContent = error.message;
        pathInput.focus();
        starting = false;
        return;
      }
      showProgress(job.job_id);
    };
    body.append(
      el("div", { class: "field" }, el("label", { for: "import-path", text: "Folder or .zip file" }), pathInput, el("span", { class: "hint", text: "Images are copied into this project. Duplicates are skipped. Nothing leaves your computer." })),
      problem,
      el("div", { class: "dlg-foot flush" },
        el("button", { class: "btn", type: "button", text: "Cancel", onclick: () => handle.close("cancel") }),
        el("button", { class: "btn btn-primary", type: "button", text: "Start import", onclick: start })),
    );
    pathInput.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); start(); } });
    handle = openDialog({ title: "Import images", body });
    pathInput.focus();

    function showProgress(jobId) {
      const bar = el("div", { class: "progress", role: "progressbar", "aria-label": "Import progress", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "0" }, el("div"));
      const status = el("p", { class: "num", role: "status", text: "Starting…" });
      const hide = el("button", { class: "btn", type: "button", text: "Hide", onclick: () => handle.close("hidden") });
      const cancel = el("button", {
        class: "btn btn-danger", type: "button", text: "Cancel import",
        onclick: async () => {
          cancel.disabled = true;
          status.textContent = "Cancelling… images already imported are kept.";
          try {
            await api(`/api/jobs/${jobId}/cancel`, { method: "POST" });
          } catch (error) {
            cancel.disabled = false;
            toast(error.message, { error: true });
          }
        },
      });
      body.replaceChildren(
        status, bar,
        el("p", { class: "hint", text: "You can hide this window; the import keeps running. Cancelling keeps the images already imported." }),
        el("div", { class: "dlg-foot flush" }, cancel, hide),
      );
      watchJob(jobId, (job) => {
        const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
        bar.firstChild.style.width = `${pct}%`;
        bar.setAttribute("aria-valuenow", String(pct));
        if (job.cancel_requested) return; // keep the "Cancelling…" message
        status.textContent = job.state === "queued" ? "Waiting to start…" : `${job.done.toLocaleString()} of ${job.total.toLocaleString()} files checked`;
      }).then(async (job) => {
        await loadProject();
        renderFilters();
        await loadPage(true);
        if (job.state === "failed") {
          toast(`Import failed: ${job.error}`, { error: true });
          if (handle.dialog.isConnected) { status.textContent = `Import failed: ${job.error}`; hide.textContent = "Close"; }
          return;
        }
        const r = job.report;
        toast(r.cancelled
          ? `Import cancelled. ${plural(r.added, "image")} kept.`
          : `Imported ${plural(r.added, "image")}${r.duplicates ? `, skipped ${plural(r.duplicates, "duplicate")}` : ""}`);
        if (handle.dialog.isConnected) showSummary(r);
      });
    }

    function showSummary(r) {
      const stat = (n, label) => el("div", { class: "stat" }, el("b", { text: n.toLocaleString() }), el("span", { text: label }));
      body.replaceChildren(
        ...(r.cancelled ? [el("p", { role: "status", text: `Import cancelled. The ${plural(r.added, "image")} imported before you cancelled were kept.` })] : []),
        el("div", { class: "stats" }, stat(r.added, "Added"), stat(r.duplicates, "Duplicates skipped"), stat(r.corrupt, "Unreadable"), stat(r.oversize, "Too large"), stat(r.unsupported, "Other files ignored")),
        ...(r.problems.length
          ? [el("details", {}, el("summary", { text: `Show ${plural(r.problems.length + r.problems_dropped, "problem")}` }),
              el("ul", {}, ...r.problems.map((p) => el("li", { text: `${p.path} — ${p.reason}` })),
                r.problems_dropped ? el("li", { text: `…and ${r.problems_dropped.toLocaleString()} more` }) : null))]
          : []),
        el("div", { class: "dlg-foot flush" }, el("button", { class: "btn btn-primary", type: "button", text: "Done", onclick: () => handle.close("done") })),
      );
    }
  }

  // ---- auto split ------------------------------------------------------------------------
  function openAutoSplit() {
    const c = state.project.split_counts;
    const inputs = {};
    const fields = el("div", { class: "row" });
    for (const [name, value] of [["train", 80], ["val", 10], ["test", 10]]) {
      inputs[name] = el("input", { class: "input", id: `r-${name}`, type: "number", min: "0", max: "100", step: "any", value: String(value), inputmode: "decimal" });
      fields.append(el("div", { class: "field grow-field" }, el("label", { for: `r-${name}`, text: `${SPLIT_LABEL[name]} %` }), inputs[name]));
    }
    const only = el("input", { type: "checkbox", id: "only-unassigned", checked: true });
    const seed = el("input", { class: "input", id: "seed", type: "number", step: "1", value: "42" });
    const total = el("p", { class: "num", role: "status" });
    const problem = el("p", { class: "error-text", role: "alert" });
    const sum = () => SPLITS.reduce((acc, name) => acc + Number(inputs[name].value || 0), 0);
    const isHundred = () => Math.abs(sum() - 100) < 0.001; // decimals like 33.3 + 33.3 + 33.4 are fine
    const update = () => { total.textContent = `Total: ${Math.round(sum() * 100) / 100}%`; total.className = isHundred() ? "num muted" : "num error-text"; };
    for (const input of Object.values(inputs)) input.addEventListener("input", update);
    update();
    let handle;
    const apply = async () => {
      problem.textContent = "";
      if (!isHundred()) { problem.textContent = "The three percentages must add up to 100."; return; }
      try {
        const result = await api(`/api/projects/${projectId}/split/auto`, {
          method: "POST",
          body: { ratios: Object.fromEntries(SPLITS.map((n) => [n, Number(inputs[n].value) / 100])), seed: Number(seed.value), only_unassigned: only.checked },
        });
        handle.close("done");
        const n = Object.values(result.assigned).reduce((a, b) => a + b, 0);
        await refreshProjectCounts();
        await loadPage(true);
        toast(`Assigned splits to ${plural(n, "image")}`, { actionLabel: "Undo", onAction: () => undoAutoSplit(result.previous) });
      } catch (error) {
        problem.textContent = error.message;
      }
    };
    handle = openDialog({
      title: "Split images into train / validation / test",
      body: [
        el("p", { class: "muted num", text: `Now: ${c.train} train · ${c.val} validation · ${c.test} test · ${c.unassigned} without a split` }),
        fields, total,
        el("label", { class: "row", for: "only-unassigned" }, only, "Only images that don’t have a split yet"),
        el("details", {}, el("summary", { text: "Advanced" }), el("div", { class: "field" }, el("label", { for: "seed", text: "Random seed (same seed → same result)" }), seed)),
        problem,
      ],
      actions: [{ label: "Cancel", onClick: (close) => close("cancel") }, { label: "Assign splits", primary: true, onClick: apply }],
    });
    document.getElementById("r-train")?.focus();
  }

  async function undoAutoSplit(previous) {
    try {
      for (const [name, ids] of Object.entries(previous)) {
        if (ids.length) await api(`/api/projects/${projectId}/split`, { method: "PUT", body: { image_ids: ids, split: name === "unassigned" ? null : name } });
      }
      toast("Splits restored");
    } catch (error) {
      toast(error.message, { error: true });
    }
    await refreshProjectCounts();
    await loadPage(true);
  }

  // ---- annotate and classes --------------------------------------------------------------
  async function startAnnotating() {
    try {
      let page = await api(`/api/projects/${projectId}/images?labelled=false&limit=1`);
      if (!page.items.length) page = await api(`/api/projects/${projectId}/images?limit=1`);
      if (!page.items.length) { toast("Import some images first."); return; }
      navigate(`/projects/${projectId}/annotate/${page.items[0].id}`);
    } catch (error) {
      toast(error.message, { error: true });
    }
  }
  function openClasses() {
    openClassManager({
      projectId,
      onChanged: async () => { await loadProject(); renderFilters(); await loadPage(true); },
    });
  }

  // ---- start -----------------------------------------------------------------------------
  const cleanup = () => {
    document.removeEventListener("keydown", onKey);
    observer.disconnect();
  };
  try {
    await loadProject();
  } catch (error) {
    container.replaceChildren(
      el("div", { class: "empty", role: "alert" }, el("h3", { text: error.status === 404 ? "Project not found" : "Could not open this project" }), el("p", { text: error.message }), el("a", { class: "btn btn-primary", href: "#/projects", text: "Back to Projects" })),
    );
    setToolbar({ title: "Project" });
    return cleanup; // the listeners above were already registered; remove them on leaving
  }
  setToolbar({
    title: state.project.name,
    actions: [
      el("a", { class: "btn btn-quiet", href: "#/projects" }, icon("back"), "Projects"),
      el("button", { class: "btn", type: "button", onclick: openAutoSplit }, icon("shuffle"), "Split…"),
      el("button", { class: "btn", type: "button", onclick: openClasses }, "Classes…"),
      el("button", { class: "btn", type: "button", onclick: openImport }, icon("upload"), "Import images"),
      el("button", { class: "btn", type: "button", onclick: openExport }, "Export…"),
      el("button", { class: "btn", type: "button", onclick: openLabelImport }, "Import labels…"),
      el("button", { class: "btn btn-primary", type: "button", onclick: startAnnotating }, icon("box"), "Annotate"),
    ],
    commands: [
      { label: "Annotate (next unlabelled image)", hint: "", run: startAnnotating },
      { label: "Manage classes", hint: "", run: openClasses },
      { label: "Import images", hint: "", run: openImport },
      { label: "Export labels (COCO or YOLO zip)", hint: "", run: openExport },
      { label: "Import labels (COCO or YOLO)", hint: "", run: openLabelImport },
      { label: "Split images into train / val / test", hint: "", run: openAutoSplit },
      { label: "Select all loaded images", hint: "Ctrl A", run: selectAllLoaded },
      { label: "Clear filters", hint: "", run: clearFilters },
    ],
  });
  renderFilters();
  await loadPage(true);
  return cleanup;
}
