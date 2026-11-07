// Shared UI helpers. All text is inserted with textContent / text nodes — never innerHTML —
// because file names and tags come from disk and must not be able to inject markup.

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value === null || value === undefined) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

const ICONS = {
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  plus: "M12 5v14M5 12h14",
  upload: "M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zm9 3-4.5-4.5",
  menu: "M4 7h16M4 12h16M4 17h16",
  back: "M15 5l-7 7 7 7",
  trash: "M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13",
  shuffle: "M4 7h4l8 10h4M4 17h4l2-2.5M14 9.5 16 7h4m-2-2 2 2-2 2m0 8 2-2-2-2",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4",
  keyboard: "M3 7h18v10H3zM7 11h.01M11 11h.01M15 11h.01M7 14h10",
  x: "M6 6l12 12M18 6 6 18",
  image: "M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M9 9h.01",
  cursor: "M5 3l14 7-6 2-2 6z",
  polygon: "M12 3l8 6-3 11H7L4 9z",
  box: "M4 5h16v14H4z",
  move: "M12 2v20M2 12h20M12 2l-3 3M12 2l3 3M12 22l-3-3M12 22l3-3M2 12l3-3M2 12l3 3M22 12l-3-3M22 12l-3 3",
  undo: "M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3",
  redo: "M15 14l5-5-5-5M20 9H10a6 6 0 0 0 0 12h3",
  "zoom-in": "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.5-4.5M11 8v6M8 11h6",
  "zoom-out": "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.5-4.5M8 11h6",
  fit: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  next: "M9 5l7 7-7 7",
  check: "M5 12l5 5 9-10",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  copy: "M8 8h12v12H8zM4 16V4h12",
};

export function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[name] || "");
  svg.append(path);
  return svg;
}

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDate(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function plural(count, one, many = `${one}s`) {
  return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}

// ---- toasts ------------------------------------------------------------------------------------
export function toast(message, { error = false, actionLabel = null, onAction = null } = {}) {
  const host = document.getElementById("toasts");
  // Errors use role="alert" so screen readers announce them immediately.
  const node = el("div", { class: `toast${error ? " error" : ""}`, role: error ? "alert" : false }, el("span", { text: message }));
  if (actionLabel && onAction) {
    node.append(
      el("button", {
        type: "button",
        text: actionLabel,
        onclick: () => {
          node.remove();
          onAction();
        },
      }),
    );
  }
  // The toast body lets clicks through to the page underneath (it can cover the bottom of the
  // canvas); only its buttons take clicks. Every toast can be dismissed with the x button.
  node.append(el("button", { type: "button", class: "toast-close", "aria-label": "Dismiss", text: "×", onclick: () => node.remove() }));
  host.append(node);
  while (host.children.length > 3) host.firstElementChild.remove(); // never let toasts pile up over the page
  if (!error) setTimeout(() => node.remove(), 5000); // errors stay until dismissed or pushed out
  return node;
}

// ---- dialogs -----------------------------------------------------------------------------------
// openDialog builds a <dialog>, which gives a focus trap, Esc-to-close and a backdrop for free.
let dialogCount = 0;

export function openDialog({ title, body, actions = [], className = "", onClose = null }) {
  const titleId = `dlg-title-${++dialogCount}`; // ids must be unique if dialogs ever overlap
  const dialog = el("dialog", { class: className, "aria-labelledby": titleId });
  const foot = el("div", { class: "dlg-foot" });
  const close = (result) => {
    dialog.dataset.result = result ?? "";
    dialog.close();
  };
  for (const action of actions) {
    foot.append(
      el("button", {
        type: "button",
        class: `btn ${action.primary ? "btn-primary" : ""} ${action.danger ? "btn-danger solid" : ""}`,
        text: action.label,
        onclick: () => action.onClick(close, dialog),
      }),
    );
  }
  dialog.append(
    el("div", { class: "dlg-head", id: titleId, text: title }),
    el("div", { class: "dlg-body" }, body),
    ...(actions.length ? [foot] : []), // append(null) would print the word "null"
  );
  dialog.addEventListener("close", () => {
    dialog.remove();
    if (onClose) onClose(dialog.dataset.result);
  });
  document.body.append(dialog);
  dialog.showModal();
  return { dialog, close };
}

export function confirmDialog({ title, message, confirmLabel, danger = false }) {
  return new Promise((resolve) => {
    openDialog({
      title,
      body: el("p", { text: message }),
      actions: [
        { label: "Cancel", onClick: (close) => close("cancel") },
        { label: confirmLabel, primary: !danger, danger, onClick: (close) => close("ok") },
      ],
      onClose: (result) => resolve(result === "ok"),
    });
  });
}

// ---- theme -------------------------------------------------------------------------------------
const THEME_KEY = "studio.theme";

export function getTheme() {
  try {
    return localStorage.getItem(THEME_KEY) || "system";
  } catch {
    return "system";
  }
}

export function setTheme(theme) {
  const root = document.documentElement;
  if (theme === "light" || theme === "dark") root.dataset.theme = theme;
  else delete root.dataset.theme;
  try {
    if (theme === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* storage unavailable: the theme still applies for this page view */
  }
}

export function isTyping(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

// ---- radio groups: one Tab stop, arrow keys move and select (WAI-ARIA radio group pattern) ---
export function rovingTabindex(group) {
  if (!group) return;
  const items = [...group.querySelectorAll('[role="radio"]')];
  const checked = items.find((item) => item.getAttribute("aria-checked") === "true") ?? items[0];
  for (const item of items) item.tabIndex = item === checked ? 0 : -1;
}

export function enableRadioArrows(group) {
  if (!group) return;
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
  group.addEventListener("keydown", (event) => {
    if (!(event.key in step)) return;
    const items = [...group.querySelectorAll('[role="radio"]')];
    const index = items.indexOf(document.activeElement);
    if (index < 0) return;
    event.preventDefault();
    const next = items[(index + step[event.key] + items.length) % items.length];
    next.focus();
    next.click();
  });
}
