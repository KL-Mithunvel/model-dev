// Projects list: create, open, delete.
import { api } from "../api.js";
import { confirmDialog, el, formatDate, icon, openDialog, plural, toast } from "../ui.js";

function splitSummary(counts) {
  const row = el("div", { class: "split-row" });
  for (const name of ["train", "val", "test", "unassigned"]) {
    row.append(
      el("span", {}, el("i", { class: `dot ${name}` }), `${counts[name].toLocaleString()} ${name}`),
    );
  }
  return row;
}

export function newProjectDialog(onCreated) {
  const input = el("input", {
    class: "input",
    id: "project-name",
    type: "text",
    maxlength: "80",
    autocomplete: "off",
    placeholder: "e.g. Warehouse pallets",
  });
  const problem = el("p", { class: "error-text", role: "alert" });
  const submit = async (close) => {
    problem.textContent = "";
    try {
      const project = await api("/api/projects", { method: "POST", body: { name: input.value } });
      close("created");
      toast(`Created “${project.name}”`);
      onCreated(project);
    } catch (error) {
      problem.textContent = error.message;
      input.focus();
    }
  };
  const handle = openDialog({
    title: "New project",
    body: [
      el("div", { class: "field" }, el("label", { for: "project-name", text: "Project name" }), input),
      problem,
    ],
    actions: [
      { label: "Cancel", onClick: (close) => close("cancel") },
      { label: "Create project", primary: true, onClick: submit },
    ],
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      submit(handle.close);
    }
  });
  input.focus();
}

export async function mount(container, { setToolbar, navigate }) {
  setToolbar({ title: "Projects" });
  const page = el("div", { class: "page" });
  container.replaceChildren(page);
  page.append(el("div", { class: "state-box", text: "Loading projects…" }));

  const openNew = () => newProjectDialog((project) => navigate(`/projects/${project.id}`));
  setToolbar({
    title: "Projects",
    actions: [
      el("button", { class: "btn btn-primary", type: "button", onclick: openNew }, icon("plus"), "New project"),
    ],
  });

  async function load() {
    let projects;
    try {
      projects = await api("/api/projects");
    } catch (error) {
      page.replaceChildren(
        el(
          "div",
          { class: "state-box", role: "alert" },
          el("p", { text: error.message }),
          el("button", { class: "btn", type: "button", text: "Try again", onclick: load }),
        ),
      );
      return;
    }
    if (!projects.length) {
      page.replaceChildren(
        el(
          "div",
          { class: "empty" },
          icon("image"),
          el("h3", { text: "Create your first project" }),
          el("p", {
            text: "A project holds your images and, later, their labels and trained models. Everything stays on this computer.",
          }),
          el("button", { class: "btn btn-primary", type: "button", onclick: openNew }, icon("plus"), "New project"),
        ),
      );
      return;
    }
    const cards = el("div", { class: "cards" });
    for (const project of projects) {
      const remove = async () => {
        const ok = await confirmDialog({
          title: `Delete “${project.name}”?`,
          message: `This permanently deletes ${plural(project.image_count, "image")} copied into this project and all their tags and splits. Your original files are not touched. This cannot be undone.`,
          confirmLabel: "Delete project",
          danger: true,
        });
        if (!ok) return;
        try {
          await api(`/api/projects/${project.id}`, { method: "DELETE" });
          toast(`Deleted “${project.name}”`);
          load();
        } catch (error) {
          toast(error.message, { error: true });
        }
      };
      cards.append(
        el(
          "article",
          { class: "card" },
          el(
            "a",
            { class: "card-link", href: `#/projects/${project.id}` },
            el("h3", { text: project.name }),
            el("span", { class: "muted num", text: `${plural(project.image_count, "image")} · created ${formatDate(project.created_at)}` }),
          ),
          splitSummary(project.split_counts),
          el(
            "div",
            { class: "card-foot" },
            el("a", { class: "btn", href: `#/projects/${project.id}`, text: "Open" }),
            el("button", { class: "btn btn-quiet btn-danger", type: "button", onclick: remove, "aria-label": `Delete project ${project.name}` }, icon("trash"), "Delete…"),
          ),
        ),
      );
    }
    page.replaceChildren(
      el("div", { class: "page-head" }, el("h2", { text: "Projects" }), el("span", { class: "muted num", text: plural(projects.length, "project") })),
      cards,
    );
  }
  await load();
  return () => {};
}
