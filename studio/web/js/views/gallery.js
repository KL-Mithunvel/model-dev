// Project gallery: thumbnails, filters, selection, inspector (split + tags), import, auto-split.
import { api, watchJob } from "../api.js";
import { el, formatBytes, formatDate, icon, isTyping, openDialog, plural, toast } from "../ui.js";

const SPLITS = ["train", "val", "test"];
const SPLIT_LABEL = { train: "Train", val: "Validation", test: "Test" };

export async function mount(container, { setToolbar, projectId }) {
  const state = {
    project: null,
    items: [],
    total: 0,
    filters: { split: "", tag: "", q: "" },
    selection: new Set(),
    anchor: null,
    focusIndex: 0,
    tags: [],
    loading: false,
    token: 0,
    pageSize: 60,
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
    try {
      const page = await api(query(state.items.length));
      if (token !== state.token) return; // a newer request superseded this one
      state.pageSize = page.limit;
      state.total = page.total;
      state.items.push(...page.items);
    } catch (error) {
      if (token !== state.token) return;
      state.loading = false;
      grid.replaceChildren(
        el("div", { class: "state-box", role: "alert" }, el("p", { text: error.message }), el("button", { class: "btn", type: "button", text: "Try again", onclick: () => loadPage(true) })),
      );
      return;
    }
    state.loading = false;
    renderAll();
  }

  // ---- rendering -------------------------------------------------------------------------
  function selectedItems() {
    return state.items.filter((item) => state.selection.has(item.id));
  }

  function renderFilters() {
    const splitSelect = el("select", { class: "input", id: "f-split", "aria-label": "Filter by split", onchange: (e) => { state.filters.split = e.target.value; loadPage(true); } },
      el("option", { value: "", text: "All splits" }),
      ...[...SPLITS, "unassigned"].map((s) => el("option", { value: s, text: s === "unassigned" ? "No split" : SPLIT_LABEL[s], selected: state.filters.split === s })),
    );
    const tagSelect = el("select", { class: "input", id: "f-tag", "aria-label": "Filter by tag", onchange: (e) => { state.filters.tag = e.target.value; loadPage(true); } },
      el("option", { value: "", text: "All tags" }),
      ...state.tags.map((t) => el("option", { value: t.tag, text: `${t.tag} (${t.count})`, selected: state.filters.tag === t.tag })),
    );
    let timer = null;
    const search = el("input", {
      class: "input search", id: "f-search", type: "search", placeholder: "Search file names", "aria-label": "Search file names", value: state.filters.q,
      oninput: (e) => {
        clearTimeout(timer);
        timer = setTimeout(() => { state.filters.q = e.target.value.trim(); loadPage(true); }, 250);
      },
    });
    const active = Object.values(state.filters).some(Boolean);
    filtersBar.replaceChildren(
      splitSelect, tagSelect, search,
      ...(active ? [el("button", { class: "btn btn-quiet", type: "button", text: "Clear filters", onclick: clearFilters })] : []),
      el("span", { class: "muted num", id: "summary", role: "status" }),
    );
  }

  function clearFilters() {
    state.filters = { split: "", tag: "", q: "" };
    renderFilters();
    loadPage(true);
  }

  function updateSummary() {
    const node = document.getElementById("summary");
    if (!node) return;
    const sel = state.selection.size ? ` · ${state.selection.size.toLocaleString()} selected` : "";
    node.textContent = `${state.items.length.toLocaleString()} of ${state.total.toLocaleString()} shown${sel}`;
  }

  function tileLabel(item) {
    const parts = [item.original_name, item.split ? `${SPLIT_LABEL[item.split]} split` : "no split"];
    if (item.tags.length) parts.push(`tags: ${item.tags.join(", ")}`);
    return parts.join(", ");
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
    refreshTiles();
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

  function refreshTiles() {
    for (const tile of grid.querySelectorAll(".tile")) {
      const item = state.items[Number(tile.dataset.index)];
      if (!item) continue;
      const fresh = renderTile(item, Number(tile.dataset.index));
      tile.replaceWith(fresh);
    }
    renderInspector();
  }

  function splitControl(items) {
    const current = new Set(items.map((i) => i.split || ""));
    const group = el("div", { class: "seg", role: "group", "aria-label": "Split" });
    for (const [value, label] of [["train", "Train"], ["val", "Val"], ["test", "Test"], ["", "None"]]) {
      group.append(
        el("button", { type: "button", text: label, "aria-pressed": String(current.size === 1 && current.has(value)), onclick: () => applySplit(items, value || null) }),
      );
    }
    return group;
  }

  function tagEditor(item) {
    const box = el("div", { class: "tag-box" });
    const input = el("input", { type: "text", "aria-label": "Add a tag", placeholder: item.tags.length ? "" : "Add a tag…", maxlength: "40", list: "tag-suggestions" });
    const suggestions = el("datalist", { id: "tag-suggestions" }, ...state.tags.map((t) => el("option", { value: t.tag })));
    const save = async (tags) => {
      try {
        const result = await api(`/api/images/${item.id}/tags`, { method: "PUT", body: { tags } });
        item.tags = result.tags;
        state.tags = await api(`/api/projects/${projectId}/tags`);
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
        el("img", { src: item.file_url, alt: `Preview of ${item.original_name}` }),
        el("h3", { text: item.original_name }),
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

  grid.addEventListener("click", (event) => {
    const tile = event.target.closest(".tile");
    if (!tile) return;
    state.focusIndex = Number(tile.dataset.index);
    select(state.focusIndex, event);
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
  function openImport() {
    const body = el("div", { class: "stack" });
    const pathInput = el("input", { class: "input", id: "import-path", type: "text", autocomplete: "off", placeholder: String.raw`C:\Users\me\Pictures\photos   or   D:\data\photos.zip` });
    const problem = el("p", { class: "error-text", role: "alert" });
    let handle;
    const start = async () => {
      problem.textContent = "";
      let job;
      try {
        job = await api(`/api/projects/${projectId}/imports`, { method: "POST", body: { path: pathInput.value.trim() } });
      } catch (error) {
        problem.textContent = error.message;
        pathInput.focus();
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
      body.replaceChildren(
        status, bar,
        el("p", { class: "hint", text: "You can hide this window; the import keeps running. It cannot be cancelled yet." }),
        el("div", { class: "dlg-foot flush" }, hide),
      );
      watchJob(jobId, (job) => {
        const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
        bar.firstChild.style.width = `${pct}%`;
        bar.setAttribute("aria-valuenow", String(pct));
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
        toast(`Imported ${plural(r.added, "image")}${r.duplicates ? `, skipped ${plural(r.duplicates, "duplicate")}` : ""}`);
        if (handle.dialog.isConnected) showSummary(r);
      });
    }

    function showSummary(r) {
      const stat = (n, label) => el("div", { class: "stat" }, el("b", { text: n.toLocaleString() }), el("span", { text: label }));
      body.replaceChildren(
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
      inputs[name] = el("input", { class: "input", id: `r-${name}`, type: "number", min: "0", max: "100", step: "1", value: String(value), inputmode: "numeric" });
      fields.append(el("div", { class: "field grow-field" }, el("label", { for: `r-${name}`, text: `${SPLIT_LABEL[name]} %` }), inputs[name]));
    }
    const only = el("input", { type: "checkbox", id: "only-unassigned", checked: true });
    const seed = el("input", { class: "input", id: "seed", type: "number", step: "1", value: "42" });
    const total = el("p", { class: "num", role: "status" });
    const problem = el("p", { class: "error-text", role: "alert" });
    const sum = () => SPLITS.reduce((acc, name) => acc + Number(inputs[name].value || 0), 0);
    const update = () => { total.textContent = `Total: ${sum()}%`; total.className = sum() === 100 ? "num muted" : "num error-text"; };
    for (const input of Object.values(inputs)) input.addEventListener("input", update);
    update();
    let handle;
    const apply = async () => {
      problem.textContent = "";
      if (sum() !== 100) { problem.textContent = "The three percentages must add up to 100."; return; }
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

  // ---- start -----------------------------------------------------------------------------
  try {
    await loadProject();
  } catch (error) {
    container.replaceChildren(
      el("div", { class: "empty", role: "alert" }, el("h3", { text: error.status === 404 ? "Project not found" : "Could not open this project" }), el("p", { text: error.message }), el("a", { class: "btn btn-primary", href: "#/projects", text: "Back to Projects" })),
    );
    setToolbar({ title: "Project" });
    return () => {};
  }
  setToolbar({
    title: state.project.name,
    actions: [
      el("a", { class: "btn btn-quiet", href: "#/projects" }, icon("back"), "Projects"),
      el("button", { class: "btn", type: "button", onclick: openAutoSplit }, icon("shuffle"), "Split…"),
      el("button", { class: "btn btn-primary", type: "button", onclick: openImport }, icon("upload"), "Import images"),
    ],
    commands: [
      { label: "Import images", hint: "", run: openImport },
      { label: "Split images into train / val / test", hint: "", run: openAutoSplit },
      { label: "Select all loaded images", hint: "Ctrl A", run: selectAllLoaded },
      { label: "Clear filters", hint: "", run: clearFilters },
    ],
  });
  renderFilters();
  await loadPage(true);
  return () => {
    document.removeEventListener("keydown", onKey);
    observer.disconnect();
  };
}
