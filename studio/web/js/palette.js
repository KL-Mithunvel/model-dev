// Command palette (Ctrl/Cmd+K) and the shortcut cheat sheet (?).
import { el, openDialog } from "./ui.js";

export const SHORTCUTS = [
  ["Command palette", ["Ctrl", "K"]],
  ["Shortcut sheet", ["?"]],
  ["Select all loaded images", ["Ctrl", "A"]],
  ["Move between images", ["←", "→", "↑", "↓"]],
  ["Select / deselect image", ["Space"]],
  ["Add to selection", ["Ctrl", "Click"]],
  ["Select a range", ["Shift", "Click"]],
  ["Clear selection", ["Esc"]],
  ["Focus search", ["/"]],
];

export function showShortcuts() {
  const grid = el("div", { class: "shortcuts" });
  for (const [label, keys] of SHORTCUTS) {
    grid.append(
      el("span", { text: label }),
      el("span", {}, keys.map((key) => el("kbd", { text: key }))),
    );
  }
  openDialog({
    title: "Keyboard shortcuts",
    body: grid,
    actions: [{ label: "Done", primary: true, onClick: (close) => close("done") }],
  });
}

// commands: [{label, hint, run}] — evaluated each time the palette opens so it can be context-aware.
export function openPalette(commands) {
  let filtered = commands;
  let active = 0;
  const input = el("input", {
    class: "input",
    type: "text",
    placeholder: "Type a command…",
    "aria-label": "Command",
    role: "combobox",
    "aria-expanded": "true",
    "aria-controls": "palette-list",
  });
  const list = el("ul", { id: "palette-list", role: "listbox" });

  const render = () => {
    list.replaceChildren();
    if (!filtered.length) {
      list.append(el("li", { class: "state-box", text: "No matching command" }));
      return;
    }
    filtered.forEach((command, index) => {
      const button = el(
        "button",
        {
          type: "button",
          role: "option",
          "aria-selected": String(index === active),
          tabindex: "-1",
          onclick: () => run(command),
        },
        el("span", { text: command.label }),
        el("span", { class: "muted", text: command.hint || "" }),
      );
      list.append(el("li", {}, button));
      if (index === active) button.scrollIntoView({ block: "nearest" });
    });
  };

  let handle;
  const run = (command) => {
    handle.close("run");
    command.run();
  };

  input.addEventListener("input", () => {
    const needle = input.value.trim().toLowerCase();
    filtered = commands.filter((command) => command.label.toLowerCase().includes(needle));
    active = 0;
    render();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      active = Math.min(active + 1, filtered.length - 1);
      render();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      active = Math.max(active - 1, 0);
      render();
    } else if (event.key === "Enter" && filtered[active]) {
      event.preventDefault();
      run(filtered[active]);
    }
  });

  handle = openDialog({
    title: "Command palette",
    className: "palette",
    body: [input, list],
  });
  render();
  input.focus();
}
