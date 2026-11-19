// Hardware monitor: live charts on one shared time axis, warnings with a fix, and recorded runs.
// Live data arrives over a WebSocket (new samples only) and falls back to polling if it cannot connect.
import { api } from "../api.js";
import { axisMax, formatDuration, formatValue, latestValue, pathData, segments, windowLabel } from "../chart.js";
import { confirmDialog, el, formatDate, openDialog, plural, toast } from "../ui.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const CHART_W = 600;
const CHART_H = 120;
const GRID_LINES = [0.25, 0.5, 0.75];
const GAP_FACTOR = 2.5; // a pause longer than this many sampling periods breaks the line

// What each card draws. A card appears only if its first series exists in the catalog.
const CHARTS = [
  { id: "cpu", title: "CPU", series: [{ key: "cpu.total", name: "All cores" }], fixedMax: 100 },
  { id: "ram", title: "Memory", series: [{ key: "ram.percent", name: "In use" }], fixedMax: 100, detail: "ram.used" },
  { id: "disk", title: "Disk", series: [{ key: "disk.read", name: "Read" }, { key: "disk.write", name: "Write", dashed: true }], floor: 10 },
  { id: "gpu-util", title: "GPU usage", series: [{ key: "gpu0.util", name: "Usage" }], fixedMax: 100, gpu: true },
  { id: "gpu-vram", title: "GPU memory", series: [{ key: "gpu0.vram_used", name: "In use" }], maxFromCatalog: true, gpu: true },
  { id: "gpu-temp", title: "GPU temperature", series: [{ key: "gpu0.temp", name: "Temperature" }], floor: 100, gpu: true },
  { id: "gpu-power", title: "GPU power", series: [{ key: "gpu0.power", name: "Power" }], floor: 10, gpu: true },
];

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}

/** One chart card. `update(samples, frame)` redraws it; the same card draws live and stored data. */
function chartCard(definition, catalog) {
  const unit = catalog[definition.series[0].key]?.unit ?? "";
  const lines = definition.series.map((series) =>
    svg("path", { class: `chart-line${series.dashed ? " dashed" : ""}`, "vector-effect": "non-scaling-stroke" }),
  );
  const plot = svg("svg", { class: "chart", viewBox: `0 0 ${CHART_W} ${CHART_H}`, preserveAspectRatio: "none", "aria-hidden": "true" });
  for (const fraction of GRID_LINES) {
    plot.append(svg("line", { class: "chart-grid", x1: 0, x2: CHART_W, y1: CHART_H * fraction, y2: CHART_H * fraction, "vector-effect": "non-scaling-stroke" }));
  }
  plot.append(...lines);
  const value = el("span", { class: "chart-value" });
  const top = el("span", { class: "chart-top" });
  const start = el("span", { class: "chart-start" });
  const legend = definition.series.length > 1
    ? el("div", { class: "chart-legend" }, definition.series.map((series) =>
        el("span", {}, el("i", { class: `swatch${series.dashed ? " dashed" : ""}` }), series.name)))
    : null;
  const node = el(
    "section",
    { class: "card chart-card", "data-chart": definition.id, role: "img", "aria-label": definition.title },
    el("div", { class: "chart-head" }, el("h3", { text: definition.title }), value),
    el("div", { class: "chart-plot" }, plot, top),
    el("div", { class: "chart-foot" }, start, el("span", { text: "now" })),
    legend,
  );

  function update(samples, { endT, windowS, gapS }) {
    const keys = definition.series.map((series) => series.key);
    const known = definition.fixedMax ?? (definition.maxFromCatalog ? catalog[keys[0]]?.max : null);
    const yMax = axisMax(samples, keys, known, definition.floor ?? 1);
    definition.series.forEach((series, index) => {
      lines[index].setAttribute("d", pathData(segments(samples, series.key, { endT, windowS, width: CHART_W, height: CHART_H, yMax, gapS })));
    });
    const readout = definition.series
      .map((series) => {
        const current = latestValue(samples, series.key);
        return definition.series.length > 1 ? `${series.name} ${formatValue(current, unit)}` : formatValue(current, unit);
      })
      .join(" · ");
    let extra = "";
    if (definition.detail) {
      const used = latestValue(samples, definition.detail);
      if (used !== null) extra = ` (${formatValue(used, catalog[definition.detail]?.unit ?? "")})`;
    }
    value.textContent = readout + extra;
    top.textContent = formatValue(yMax, unit);
    start.textContent = `${windowLabel(Math.round(windowS))} ago`;
    node.setAttribute("aria-label", `${definition.title}: ${readout}${extra}`);
  }
  return { node, update };
}

function noticeFor(warning) {
  return el(
    "div",
    { class: `notice ${warning.severity}`, "data-warning": warning.id },
    el("strong", { text: warning.severity === "warning" ? "Warning: " : "Note: " }),
    warning.message,
    el("p", { class: "hint", text: `What to do: ${warning.fix}` }),
  );
}

function runDialog(runId) {
  const body = el("div", { class: "stack" }, el("p", { class: "hint", text: "Loading…" }));
  openDialog({ title: "Recorded run", className: "wide", body: [body], actions: [{ label: "Close", primary: true, onClick: (close) => close("done") }] });
  api(`/api/monitor/runs/${runId}`).then(
    (run) => {
      try {
      const last = run.samples.length ? run.samples[run.samples.length - 1].t : 0;
      const frame = { endT: last, windowS: Math.max(last, run.interval_s), gapS: run.interval_s * GAP_FACTOR };
      const grid = el("div", { class: "chart-grid-wrap" });
      for (const definition of CHARTS) {
        if (!run.catalog[definition.series[0].key]) continue;
        const card = chartCard(definition, run.catalog);
        card.update(run.samples, frame);
        grid.append(card.node);
      }
      const rows = Object.entries(run.summary)
        .filter(([key]) => !key.startsWith("cpu.core."))
        .map(([key, stats]) => {
          const unit = run.catalog[key]?.unit ?? "";
          return el("tr", {}, el("td", { text: run.catalog[key]?.label ?? key }), el("td", { text: formatValue(stats.avg, unit) }), el("td", { text: formatValue(stats.max, unit) }));
        });
      body.replaceChildren(
        el("p", { class: "hint", text: `“${run.name}” · ${formatDate(run.started_at)} · ${run.status}${run.truncated ? " · stopped storing early (run too long)" : ""}` }),
        run.samples.length ? grid : el("p", { class: "hint", text: "This run stored no samples (it was stopped too quickly)." }),
        ...(rows.length ? [el("table", { class: "table", "data-summary": "" }, el("thead", {}, el("tr", {}, el("th", { text: "Reading" }), el("th", { text: "Average" }), el("th", { text: "Peak" }))), el("tbody", {}, rows))] : []),
      );
      } catch (error) {
        console.error(error);
        body.replaceChildren(el("p", { class: "error-text", role: "alert", text: `This run could not be shown (${error.message}).` }));
      }
    },
    (error) => body.replaceChildren(el("p", { class: "error-text", role: "alert", text: error.message })),
  );
}

export async function mount(container, { setToolbar }) {
  setToolbar({ title: "Hardware" });
  const page = el("div", { class: "page monitor" });
  container.replaceChildren(page);
  page.append(el("div", { class: "state-box", text: "Reading the hardware…" }));

  let status;
  try {
    status = await api("/api/monitor/status");
  } catch (error) {
    page.replaceChildren(el("div", { class: "state-box", role: "alert" }, el("p", { text: error.message })));
    return undefined;
  }
  const initial = await api(`/api/monitor/samples?seconds=${status.buffer_seconds}`);

  let samples = initial.samples;
  let catalog = initial.catalog;
  let warnings = initial.warnings;
  let activeRun = initial.active_run;
  let epoch = initial.run_epoch; // run state older than our own last start/stop is stale and ignored
  let windowS = status.windows_s.includes(60) ? 60 : status.windows_s[0] ?? 60;
  let cards = []; // [{definition, card}]
  let cardKeys = "";
  let socket = null;
  let pollTimer = null;
  let stopped = false;
  let frameRequest = 0;
  let shownWarnings = null;
  let recordingText = null; // the live text of the Recording card, updated in place
  let recordingId = null; // which run the Recording card was built for

  const deviceBox = el("section", { class: "card", "data-device": "" });
  const noticeBox = el("div", { class: "stack", "aria-live": "polite" });
  const simulated = status.samplers.some((name) => name.startsWith("fake"))
    ? el("div", { class: "notice info", "data-simulated": "" }, el("strong", { text: "Note: " }), "These are simulated readings (hardware.sampler is set to a fake in config.yaml).")
    : null;
  const windowGroup = el("div", { class: "seg", role: "group", "aria-label": "Time window" });
  const grid = el("div", { class: "chart-grid-wrap", "data-charts": "" });
  const coreBox = el("section", { class: "card", "data-cores": "" });
  const recordBox = el("section", { class: "card", "data-record": "" });
  const runsBox = el("section", { class: "card", "data-runs": "" });

  function drawWindowButtons() {
    windowGroup.replaceChildren(
      ...status.windows_s.map((seconds) =>
        el("button", {
          type: "button", "data-window": String(seconds), text: windowLabel(seconds), "aria-pressed": String(seconds === windowS),
          onclick: () => { windowS = seconds; drawWindowButtons(); scheduleDraw(); },
        }),
      ),
    );
  }

  function drawDevice() {
    api("/api/monitor/status").then((fresh) => {
      if (stopped) return;
      const device = fresh.device;
      const lines = [];
      if (device.gpu_present) {
        lines.push(el("p", {}, el("strong", { text: `Training device: ${device.resolved === "cuda" ? "GPU" : "CPU"}` }), device.gpus.map((gpu) => ` · ${gpu.name}`)));
        if (device.configured !== "auto") lines.push(el("p", { class: "hint", text: `Chosen in config.yaml: hardware.device = ${device.configured}.` }));
      } else {
        lines.push(el("p", {}, el("strong", { text: "Training device: CPU" })));
        lines.push(el("p", { class: "hint", text: device.gpu_reason || "No NVIDIA GPU was found." }));
      }
      const others = Object.values(catalog).filter((entry) => !entry.available && entry.group === "gpu" && entry.reason && !device.gpu_reason.includes(entry.reason));
      for (const entry of others) lines.push(el("p", { class: "hint", text: `${entry.label}: ${entry.reason}` }));
      deviceBox.replaceChildren(el("h3", { text: "Compute" }), ...lines);
    }, () => {});
  }

  function ensureCards() {
    const keys = Object.entries(catalog).filter(([, entry]) => entry.available).map(([key]) => key).join("|");
    if (keys === cardKeys) return;
    cardKeys = keys;
    cards = CHARTS.filter((definition) => catalog[definition.series[0].key]?.available).map((definition) => ({ definition, card: chartCard(definition, catalog) }));
    grid.replaceChildren(...cards.map(({ card }) => card.node));
    if (!cards.some(({ definition }) => definition.gpu)) {
      const reason = catalog["gpu.nvidia"]?.reason ?? "No NVIDIA GPU was found.";
      grid.append(el("section", { class: "card", "data-no-gpu": "" }, el("h3", { text: "GPU" }), el("p", { class: "hint", text: reason }), el("p", { class: "hint", text: "The dashboard works without a GPU; training will use the CPU." })));
    }
    const coreKeys = Object.keys(catalog).filter((key) => /^cpu\.core\.\d+$/.test(key));
    coreBox.replaceChildren(
      el("h3", { text: `CPU threads (${coreKeys.length})` }),
      el("div", { class: "cores" }, coreKeys.map((key, index) => el("div", { class: "core", "data-core": key, role: "img", "aria-label": `Thread ${index}` }, el("div", { class: "bar" }, el("i")), el("span", { text: String(index) })))),
    );
  }

  function draw() {
    frameRequest = 0;
    if (stopped) return;
    ensureCards();
    const latest = samples.length ? samples[samples.length - 1] : null;
    const frame = { endT: latest ? latest.t : 0, windowS, gapS: status.interval_s * GAP_FACTOR };
    for (const { card } of cards) card.update(samples, frame);
    for (const node of coreBox.querySelectorAll(".core")) {
      const value = latest?.values[node.dataset.core];
      node.querySelector("i").style.height = `${Math.min(100, Math.max(0, value ?? 0))}%`;
      node.setAttribute("aria-label", `Thread ${node.textContent}: ${formatValue(value ?? null, "%")}`);
    }
    const noticeKey = warnings.map((w) => `${w.id}|${w.message}`).join("\n");
    if (noticeKey !== shownWarnings) { // rebuilding every second would re-announce them to screen readers
      shownWarnings = noticeKey;
      noticeBox.replaceChildren(...warnings.map(noticeFor));
    }
    drawRecord();
  }

  function scheduleDraw() {
    if (!frameRequest) frameRequest = requestAnimationFrame(draw);
  }

  function drawRecord() {
    if (activeRun) {
      const latest = samples.length ? samples[samples.length - 1].t : activeRun.started_t;
      const text = `“${activeRun.name}” · ${formatDuration(latest - activeRun.started_t)}`;
      if (recordingId !== activeRun.id || !recordingText?.isConnected) {
        // Built once per run: a button that is replaced every second can lose a click or its focus.
        recordingId = activeRun.id;
        recordingText = el("span", { "data-recording": "", text });
        recordBox.replaceChildren(
          el("h3", { text: "Recording" }),
          el("div", { class: "row" }, recordingText,
            el("button", { class: "btn btn-danger", type: "button", id: "stop-run", text: "Stop recording", onclick: stopRun })),
        );
      } else if (recordingText.textContent !== text) {
        recordingText.textContent = text;
      }
      return;
    }
    recordingId = null;
    if (recordBox.querySelector("#run-name")) return; // do not rebuild a field the user may be typing in
    const input = el("input", { class: "input", id: "run-name", type: "text", maxlength: String(status.max_run_name_length), placeholder: "e.g. Baseline training", autocomplete: "off" });
    const problem = el("p", { class: "error-text", role: "alert" });
    const start = async () => {
      problem.textContent = "";
      try {
        activeRun = await api("/api/monitor/runs", { method: "POST", body: { name: input.value } });
        epoch = Math.max(epoch, activeRun.run_epoch);
        activeRun = { id: activeRun.id, name: activeRun.name, started_t: samples.length ? samples[samples.length - 1].t : Date.now() / 1000 };
        drawRecord();
        loadRuns();
      } catch (error) {
        problem.textContent = error.message;
        input.focus();
      }
    };
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); start(); } });
    recordBox.replaceChildren(
      el("h3", { text: "Record a run" }),
      el("p", { class: "hint", text: `Saves one averaged reading every ${status.history_interval_s} seconds so you can compare runs later. Training will record one automatically.` }),
      el("div", { class: "row" }, el("div", { class: "field grow" }, el("label", { for: "run-name", text: "Run name" }), input), el("button", { class: "btn btn-primary", type: "button", id: "start-run", text: "Start recording", onclick: start })),
      problem,
    );
  }

  async function stopRun() {
    try {
      const run = await api(`/api/monitor/runs/${activeRun.id}/stop`, { method: "POST" });
      epoch = Math.max(epoch, run.run_epoch);
      activeRun = null;
      toast(`Saved “${run.name}” (${plural(run.sample_count, "reading")})`);
      drawRecord();
      loadRuns();
    } catch (error) {
      toast(error.message, { error: true });
    }
  }

  async function loadRuns() {
    let runs;
    try {
      runs = await api("/api/monitor/runs");
    } catch (error) {
      runsBox.replaceChildren(el("h3", { text: "Recorded runs" }), el("p", { class: "error-text", role: "alert", text: error.message }));
      return;
    }
    if (stopped) return;
    if (!runs.length) {
      runsBox.replaceChildren(el("h3", { text: "Recorded runs" }), el("p", { class: "hint", text: "No runs yet. Start a recording above; it stays here after the app closes." }));
      return;
    }
    const rows = runs.map((run) => {
      const length = run.sample_count ? formatDuration(run.sample_count * run.interval_s) : "–";
      return el("tr", { "data-run": String(run.id) },
        el("td", { text: run.name }),
        el("td", { text: formatDate(run.started_at) }),
        el("td", { text: run.status === "recording" ? "recording…" : run.status === "interrupted" ? `${length} (interrupted)` : length }),
        el("td", { class: "actions" },
          el("button", { class: "btn", type: "button", "data-view": "", text: "View", disabled: run.status === "recording", onclick: () => runDialog(run.id) }),
          el("button", { class: "btn btn-danger", type: "button", "data-delete": "", text: "Delete", disabled: run.status === "recording", "aria-label": `Delete ${run.name}`, onclick: () => removeRun(run) })),
      );
    });
    runsBox.replaceChildren(
      el("h3", { text: "Recorded runs" }),
      el("table", { class: "table" }, el("thead", {}, el("tr", {}, ["Name", "Started", "Length", ""].map((text) => el("th", { text })))), el("tbody", {}, rows)),
    );
  }

  async function removeRun(run) {
    const ok = await confirmDialog({ title: `Delete “${run.name}”?`, message: "Its recorded readings are removed. This cannot be undone.", confirmLabel: "Delete run", danger: true });
    if (!ok) return;
    try {
      await api(`/api/monitor/runs/${run.id}`, { method: "DELETE" });
      loadRuns();
    } catch (error) {
      toast(error.message, { error: true });
    }
  }

  // ---- live data ------------------------------------------------------------------------------
  function take(message) {
    if (message.catalog) catalog = message.catalog;
    if (message.warnings) warnings = message.warnings;
    if ("active_run" in message && message.run_epoch >= epoch) {
      epoch = message.run_epoch;
      const was = activeRun;
      activeRun = message.active_run;
      if (was && !activeRun) loadRuns(); // a run was stopped elsewhere (for example by training ending)
    }
    if (message.reset) samples = []; // the server restarted: its sample numbers began again
    samples = samples.concat(message.samples ?? []);
    const cutoff = (samples.length ? samples[samples.length - 1].t : 0) - status.buffer_seconds;
    samples = samples.filter((sample) => sample.t >= cutoff);
    scheduleDraw();
  }

  function startPolling() {
    if (pollTimer || stopped) return;
    pollTimer = setInterval(async () => {
      try {
        const after = samples.length ? samples[samples.length - 1].seq : 0;
        take(await api(`/api/monitor/samples?after=${after}`));
      } catch { /* keep trying; the next tick may work */ }
    }, status.interval_s * 1000);
  }

  function connect() {
    const after = samples.length ? samples[samples.length - 1].seq : 0;
    try {
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${location.host}/api/monitor/ws?after=${after}`);
    } catch {
      startPolling();
      return;
    }
    socket.onmessage = (event) => take(JSON.parse(event.data));
    socket.onerror = startPolling;
    socket.onclose = startPolling;
  }

  drawWindowButtons();
  page.replaceChildren(
    el("div", { class: "page-head" }, el("h2", { text: "Hardware" }), windowGroup),
    el("div", { class: "stack" }, simulated, noticeBox, deviceBox, grid, coreBox, recordBox, runsBox),
  );
  drawDevice();
  draw();
  loadRuns();
  connect();

  return () => {
    stopped = true;
    if (socket) { socket.onclose = null; socket.onerror = null; socket.close(); }
    if (pollTimer) clearInterval(pollTimer);
    if (frameRequest) cancelAnimationFrame(frameRequest);
  };
}

