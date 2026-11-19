// Dialog for dataset versions: frozen snapshots of the labelled images, their splits and classes.
import { api } from "./api.js";
import { openExportDialog } from "./labels.js";
import { confirmDialog, el, formatDate, openDialog, plural, toast } from "./ui.js";

export function openVersionsDialog({ projectId }) {
  const nameInput = el("input", { class: "input", id: "version-name", type: "text", autocomplete: "off", placeholder: "Optional name, for example: before relabelling cars" });
  const problem = el("p", { class: "error-text", role: "alert" });
  const list = el("div", { class: "stack", role: "list", "aria-label": "Versions" });
  let busy = false;

  const exportVersion = (version) => openExportDialog({
    versionId: version.id,
    title: `Export version ${version.number}`,
  });

  const removeVersion = async (version) => {
    const ok = await confirmDialog({
      title: `Delete version ${version.number}?`,
      message: "The frozen copy is removed. Your images and live labels are not touched. Its number is not reused.",
      confirmLabel: "Delete version",
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/api/versions/${version.id}`, { method: "DELETE" });
      toast(`Deleted version ${version.number}`);
      await refresh();
    } catch (error) {
      problem.textContent = error.message;
    }
  };

  const row = (version) => el("div", { class: "row", role: "listitem", "data-version": String(version.number) },
    el("span", { class: "grow" },
      el("strong", { text: `Version ${version.number}${version.name ? ` · ${version.name}` : ""}` }), el("br"),
      el("span", { class: "hint", title: version.content_hash, text: `${formatDate(version.created_at)} · ${plural(version.image_count, "image")} · ${plural(version.annotation_count, "annotation")} · fingerprint ${version.content_hash.slice(0, 12)}` })),
    el("button", { class: "btn", type: "button", onclick: () => exportVersion(version) }, "Export…"),
    el("button", { class: "btn btn-quiet", type: "button", onclick: () => removeVersion(version) }, "Delete"),
  );

  async function refresh() {
    try {
      const versions = await api(`/api/projects/${projectId}/versions`);
      list.replaceChildren(...(versions.length
        ? versions.map(row)
        : [el("p", { class: "hint", text: "No versions yet. A version freezes the labelled images, their splits and classes as they are now, so a later training run can be repeated exactly." })]));
    } catch (error) {
      problem.textContent = error.message;
    }
  }

  const create = async () => {
    if (busy) return;
    busy = true;
    problem.textContent = "";
    try {
      const version = await api(`/api/projects/${projectId}/versions`, { method: "POST", body: { name: nameInput.value } });
      nameInput.value = "";
      toast(`Created version ${version.number}`);
      await refresh();
    } catch (error) {
      problem.textContent = error.message;
    } finally {
      busy = false;
    }
  };

  nameInput.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); create(); } });
  const handle = openDialog({
    title: "Dataset versions",
    body: [
      el("div", { class: "field" },
        el("label", { for: "version-name", text: "Freeze the project as a new version" }), nameInput,
        el("span", { class: "hint", text: "Only labelled images are included. Later edits never change a version." })),
      problem,
      list,
    ],
    actions: [
      { label: "Close", onClick: (close) => close("done") },
      { label: "Create version", primary: true, onClick: create },
    ],
  });
  refresh();
  nameInput.focus();
  return handle;
}
