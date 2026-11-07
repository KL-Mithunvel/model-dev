// App shell: sidebar, toolbar, hash router, theme, global shortcuts, command palette.
import { openPalette, showShortcuts } from "./palette.js";
import { dismissNewestToast, el, getTheme, icon, isTyping, openDialog, setTheme } from "./ui.js";

const main = document.getElementById("main");
const titleNode = document.getElementById("title");
const actionsNode = document.getElementById("toolbar-actions");
const sidebar = document.getElementById("sidebar");
const menuToggle = document.getElementById("menu-toggle");

let cleanup = null;
let paletteExtras = []; // commands contributed by the current view

export function navigate(path) {
  location.hash = `#${path}`;
}

function setToolbar({ title, actions = [], commands = [] }) {
  titleNode.textContent = title;
  document.title = title === "Projects" ? "Local Vision Studio" : `${title} · Local Vision Studio`;
  actionsNode.replaceChildren(...actions);
  paletteExtras = commands;
}

function themeDialog() {
  const current = getTheme();
  const group = el("div", { class: "seg", role: "group", "aria-label": "Theme" });
  for (const [value, label] of [["system", "System"], ["light", "Light"], ["dark", "Dark"]]) {
    group.append(
      el("button", {
        type: "button",
        text: label,
        "aria-pressed": String(value === current),
        onclick: (clickEvent) => {
          setTheme(value);
          for (const button of group.children) {
            button.setAttribute("aria-pressed", String(button === clickEvent.currentTarget));
          }
        },
      }),
    );
  }
  openDialog({
    title: "Appearance",
    body: [el("p", { class: "muted", text: "System follows your operating system’s light or dark setting." }), group],
    actions: [{ label: "Done", primary: true, onClick: (close) => close("done") }],
  });
}

function buildSidebar() {
  const item = (label, iconName, props) =>
    el(props.href ? "a" : "button", { class: "nav-item", type: props.href ? undefined : "button", ...props }, icon(iconName), label);
  sidebar.replaceChildren(
    el("div", { class: "brand", text: "Vision Studio" }),
    item("Projects", "folder", { href: "#/projects", id: "nav-projects" }),
    el("div", { class: "nav-spacer" }),
    item("Appearance", "sun", { onclick: themeDialog }),
    item("Shortcuts", "keyboard", { onclick: showShortcuts }),
  );
  menuToggle.replaceChildren(icon("menu"));
}

function globalCommands() {
  return [
    { label: "Go to Projects", hint: "", run: () => navigate("/projects") },
    ...paletteExtras,
    { label: "Appearance: System / Light / Dark", hint: "", run: themeDialog },
    { label: "Show keyboard shortcuts", hint: "?", run: showShortcuts },
  ];
}

const routes = [
  { pattern: /^\/projects$/, load: () => import("./views/projects.js"), params: () => ({}) },
  { pattern: /^\/projects\/(\d+)$/, load: () => import("./views/gallery.js"), params: (m) => ({ projectId: Number(m[1]) }) },
  { pattern: /^\/projects\/(\d+)\/annotate\/(\d+)$/, load: () => import("./views/annotate.js"), params: (m) => ({ projectId: Number(m[1]), imageId: Number(m[2]) }) },
];

let routeToken = 0; // each navigation gets a number; a slower, older view must not win
let firstRoute = true;

async function route() {
  const path = location.hash.replace(/^#/, "") || "/projects";
  // In-page anchors such as "#main" (the skip link) are not routes: leave the current view alone.
  if (!path.startsWith("/")) return;
  const token = ++routeToken;
  document.body.classList.remove("nav-open");
  if (cleanup) {
    try { cleanup(); } catch { /* a view's cleanup must never block navigation */ }
    cleanup = null;
  }
  // Every view mounts into its own host. If a stale view finishes late, it only touches a host
  // that is no longer on the page.
  const host = el("div", { class: "route-host" });
  main.replaceChildren(host);
  setToolbar({ title: "Loading…" });
  const match = routes.map((r) => [r, path.match(r.pattern)]).find(([, m]) => m);
  if (!match) {
    host.append(
      el("div", { class: "empty" }, el("h3", { text: "Page not found" }), el("a", { class: "btn btn-primary", href: "#/projects", text: "Go to Projects" })),
    );
    setToolbar({ title: "Not found" });
    return;
  }
  const [definition, found] = match;
  const guardedToolbar = (config) => { if (token === routeToken) setToolbar(config); };
  try {
    const view = await definition.load();
    const viewCleanup = await view.mount(host, { setToolbar: guardedToolbar, navigate, ...definition.params(found) });
    if (token !== routeToken) {
      // The user navigated away while this view was loading: tear it down immediately.
      try { viewCleanup?.(); } catch { /* ignore */ }
      return;
    }
    cleanup = viewCleanup;
  } catch (error) {
    console.error(error);
    if (token !== routeToken) return;
    host.replaceChildren(
      el("div", { class: "state-box", role: "alert" }, el("p", { text: "This page could not be loaded." }), el("button", { class: "btn", type: "button", text: "Try again", onclick: route })),
    );
  }
  for (const link of sidebar.querySelectorAll("a.nav-item")) {
    if (path.startsWith("/projects")) link.setAttribute("aria-current", "page");
  }
  // Move focus to the new view after in-app navigation, but not on the first load: the first Tab
  // on a fresh page must reach the "Skip to content" link.
  if (!firstRoute) main.focus({ preventScroll: true });
  firstRoute = false;
}

document.addEventListener("keydown", (event) => {
  const modifier = event.ctrlKey || event.metaKey;
  if (modifier && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (!document.querySelector("dialog[open]")) openPalette(globalCommands());
  } else if (event.key === "?" && !isTyping(event.target) && !document.querySelector("dialog[open]")) {
    event.preventDefault();
    showShortcuts();
  }
});

// Escape dismisses the newest toast, unless a view already used the key (it calls preventDefault) or a
// dialog is open. Registered on window so it runs AFTER the views' document-level handlers.
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !event.defaultPrevented && !document.querySelector("dialog[open]")) dismissNewestToast();
});

menuToggle.addEventListener("click", () => {
  const open = document.body.classList.toggle("nav-open");
  menuToggle.setAttribute("aria-label", open ? "Hide navigation" : "Show navigation");
});

// The skip link jumps to the main region without touching the URL hash (the hash is the router).
document.querySelector(".skip")?.addEventListener("click", (event) => {
  event.preventDefault();
  main.focus();
});

buildSidebar();
window.addEventListener("hashchange", route);
setTheme(getTheme());
route();
