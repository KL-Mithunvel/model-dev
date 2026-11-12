// Dialog to create, rename, recolour and delete a class. Shared by the annotator and the gallery.
import { api } from "./api.js";
import { limits } from "./limits.js";
import { PRESETS, parseSkeleton, skeletonToText } from "./skeleton.js";
import { confirmDialog, el, enableRadioArrows, openDialog, plural, rovingTabindex, toast } from "./ui.js";

/**
 * existing: a class object to edit, or null to create one.
 * onChanged(kind) is called after a successful create/update/delete (kind: "created" | "updated" | "deleted").
 */
export function openClassDialog({ projectId, existing = null, onChanged }) {
  const input = el("input", {
    class: "input", id: "class-name", type: "text", autocomplete: "off",
    maxlength: String(limits.class_name_max), value: existing ? existing.name : "",
    placeholder: "e.g. forklift",
  });
  let color = existing ? existing.color : null; // null: the server picks the next palette colour
  const swatches = el("div", { class: "swatches", role: "radiogroup", "aria-label": "Colour" });
  const paintSwatches = () => {
    const hadFocus = swatches.contains(document.activeElement);
    swatches.replaceChildren(
      ...limits.palette.map((value, index) =>
        el("button", {
          type: "button", class: "swatch", role: "radio", style: `background:${value}`,
          // a hex code means nothing to a screen reader; say which swatch this is instead
          "aria-label": `Colour ${index + 1} of ${limits.palette.length}`,
          "aria-checked": String(color && color.toUpperCase() === value.toUpperCase()),
          onclick: () => { color = value; paintSwatches(); },
        }),
      ),
    );
    rovingTabindex(swatches);
    if (hadFocus) swatches.querySelector('[aria-checked="true"]')?.focus();
  };
  paintSwatches();
  enableRadioArrows(swatches);
  const problem = el("p", { class: "error-text", role: "alert" });
  let handle;

  // Keypoints (optional): the named points of one object, and which of them are joined by a line.
  const initial = skeletonToText(existing?.skeleton ?? null);
  const pointsBox = el("textarea", { class: "input", id: "class-points", rows: "6", spellcheck: "false", placeholder: "One point per line, for example:\nhead\nneck\ntail" });
  const linksBox = el("textarea", { class: "input", id: "class-links", rows: "4", spellcheck: "false", placeholder: "One connection per line, for example:\nhead - neck\nneck - tail" });
  pointsBox.value = initial.points;
  linksBox.value = initial.connections;
  const usePreset = (preset) => { const text = skeletonToText(preset); pointsBox.value = text.points; linksBox.value = text.connections; };
  const keypointFields = el("details", { class: "kp-fields", open: Boolean(existing?.skeleton) },
    el("summary", { text: "Keypoints (optional)" }),
    el("p", { class: "hint", text: "List the points of one object in the order you will click them. Needed for the keypoint tool (K)." }),
    el("div", { class: "row wrap" }, ...Object.entries(PRESETS).map(([name, preset]) => el("button", { class: "btn", type: "button", text: `Start from: ${name}`, onclick: () => usePreset(preset) }))),
    el("div", { class: "field" }, el("label", { for: "class-points", text: "Points" }), pointsBox),
    el("div", { class: "field" }, el("label", { for: "class-links", text: "Connections (drawn as lines)" }), linksBox),
  );

  const save = async () => {
    problem.textContent = "";
    const parsed = parseSkeleton(pointsBox.value, linksBox.value, { maxPoints: limits.max_keypoints, nameMax: limits.skeleton_name_max });
    if (parsed.error) {
      keypointFields.open = true;
      problem.textContent = parsed.error;
      pointsBox.focus();
      return;
    }
    const skeleton = parsed.skeleton;
    try {
      if (existing) {
        await api(`/api/classes/${existing.id}`, { method: "PATCH", body: { name: input.value, ...(color ? { color } : {}), skeleton } });
        handle.close("saved");
        toast(`Saved class “${input.value.trim()}”`);
        onChanged("updated");
      } else {
        await api(`/api/projects/${projectId}/classes`, { method: "POST", body: { name: input.value, ...(color ? { color } : {}), ...(skeleton ? { skeleton } : {}) } });
        handle.close("saved");
        toast(`Added class “${input.value.trim()}”`);
        onChanged("created");
      }
    } catch (error) {
      problem.textContent = error.message;
      input.focus();
    }
  };

  const remove = async () => {
    try {
      await api(`/api/classes/${existing.id}`, { method: "DELETE" });
      handle.close("deleted");
      toast(`Deleted class “${existing.name}”`);
      onChanged("deleted");
    } catch (error) {
      if (error.status !== 409 || !error.data?.in_use) {
        problem.textContent = error.message;
        return;
      }
      const use = error.data.in_use;
      const ok = await confirmDialog({
        title: `Delete “${existing.name}” and its annotations?`,
        message: `This class is used by ${plural(use.annotations, "annotation")} in ${plural(use.images, "image")} and as the label of ${plural(use.labels, "image")}. Deleting it permanently deletes those annotations and clears those labels. This cannot be undone.`,
        confirmLabel: use.annotations ? `Delete class and ${plural(use.annotations, "annotation")}` : "Delete class",
        danger: true,
      });
      if (!ok) return;
      try {
        await api(`/api/classes/${existing.id}?force=true`, { method: "DELETE" });
        handle.close("deleted");
        toast(`Deleted class “${existing.name}”`);
        onChanged("deleted");
      } catch (second) {
        problem.textContent = second.message;
      }
    }
  };

  handle = openDialog({
    title: existing ? `Edit class “${existing.name}”` : "New class",
    body: [
      el("div", { class: "field" }, el("label", { for: "class-name", text: "Name" }), input),
      el("div", { class: "field" }, el("span", { class: "label-text", text: "Colour" }), swatches),
      keypointFields,
      problem,
      ...(existing ? [el("button", { class: "btn btn-danger", type: "button", text: "Delete class…", onclick: remove })] : []),
    ],
    actions: [
      { label: "Cancel", onClick: (close) => close("cancel") },
      { label: existing ? "Save" : "Add class", primary: true, onClick: save },
    ],
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); save(); }
  });
  input.focus();
  input.select();
}

/** A list of the project's classes with Edit and Add. `onChanged` fires after any change. */
export function openClassManager({ projectId, onChanged }) {
  const list = el("div", { class: "stack" });
  const refresh = async () => {
    const classes = await api(`/api/projects/${projectId}/classes`);
    list.replaceChildren(
      ...(classes.length
        ? classes.map((c) =>
            el("div", { class: "a-row-head" },
              el("span", { class: "row" }, el("i", { class: "swatch-dot", style: `background:${c.color}` }), c.name,
                el("span", { class: "muted num", text: plural(c.annotations, "annotation") })),
              el("button", { class: "btn", type: "button", onclick: () => openClassDialog({ projectId, existing: c, onChanged: changed }) }, "Edit")))
        : [el("p", { class: "hint", text: "No classes yet. Add one to start annotating." })]),
    );
  };
  const changed = async (kind) => { await refresh(); await onChanged(kind); };
  openDialog({
    title: "Classes",
    body: list,
    actions: [
      { label: "Add a class", onClick: () => openClassDialog({ projectId, existing: null, onChanged: changed }) },
      { label: "Done", primary: true, onClick: (close) => close("done") },
    ],
  });
  void refresh();
}
