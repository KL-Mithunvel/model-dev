// Dialogs to export a project's labels (COCO or YOLO zip) and to import labels back.
import { api } from "./api.js";
import { el, openDialog, plural, toast } from "./ui.js";

const CHOICES = [
  { id: "coco", format: "coco", task: "detect", label: "COCO (boxes, polygons and keypoints)", hint: "One JSON file per split." },
  { id: "yolo-detect", format: "yolo", task: "detect", label: "YOLO detection (boxes)", hint: "One text file per image. Polygons and keypoints are left out." },
  { id: "yolo-segment", format: "yolo", task: "segment", label: "YOLO segmentation (polygons)", hint: "Boxes are written as 4-corner polygons." },
  { id: "yolo-pose", format: "yolo", task: "pose", label: "YOLO pose (keypoints)", hint: "Every keypoint class needs the same number of points." },
];

const query = (choice, images) => `format=${choice.format}&task=${choice.task}&images=${images}`;

export function openExportDialog({ projectId }) {
  let choice = CHOICES[0];
  let withImages = true;
  const problem = el("p", { class: "error-text", role: "alert" });
  const summary = el("p", { class: "hint", role: "status" });
  let handle;

  const refresh = async () => {
    problem.textContent = "";
    summary.textContent = "Checking…";
    try {
      const r = await api(`/api/projects/${projectId}/export/preview?${query(choice, withImages)}`);
      const notes = [];
      if (r.excluded_unlabelled) notes.push(`${plural(r.excluded_unlabelled, "unlabelled image")} left out`);
      if (r.excluded_unassigned) notes.push(`${plural(r.excluded_unassigned, "image")} without a split left out`);
      if (r.skipped_annotations) notes.push(`${plural(r.skipped_annotations, "annotation")} this format cannot hold left out`);
      const splits = Object.entries(r.splits).map(([name, n]) => `${name} ${n}`).join(", ");
      summary.textContent = `${plural(r.images, "image")} (${splits || "none"}), ${plural(r.annotations, "annotation")}.${notes.length ? ` ${notes.join("; ")}.` : ""}`;
    } catch (error) {
      summary.textContent = "";
      problem.textContent = error.message;
    }
  };

  const group = el("div", { class: "stack", role: "radiogroup", "aria-label": "Format" },
    ...CHOICES.map((c) => {
      const input = el("input", { type: "radio", name: "export-format", id: `export-${c.id}`, ...(c === choice ? { checked: true } : {}), onchange: () => { choice = c; refresh(); } });
      return el("label", { class: "row", for: `export-${c.id}` }, input, el("span", {}, el("strong", { text: c.label }), el("br"), el("span", { class: "hint", text: c.hint })));
    }),
  );
  const images = el("input", { type: "checkbox", id: "export-images", checked: true, onchange: (event) => { withImages = event.target.checked; refresh(); } });

  const download = async () => {
    problem.textContent = "";
    try {
      await api(`/api/projects/${projectId}/export/preview?${query(choice, withImages)}`); // explains a refusal in words
    } catch (error) {
      problem.textContent = error.message;
      return;
    }
    const link = el("a", { href: `/api/projects/${projectId}/export?${query(choice, withImages)}`, download: "" });
    document.body.append(link);
    link.click();
    link.remove();
    toast("Export started. Your browser will save the zip file.");
    handle.close("done");
  };

  handle = openDialog({
    title: "Export labels",
    body: [
      group,
      el("label", { class: "row", for: "export-images" }, images, "Include the images in the zip"),
      summary,
      problem,
    ],
    actions: [
      { label: "Cancel", onClick: (close) => close("cancel") },
      { label: "Download zip", primary: true, onClick: download },
    ],
  });
  refresh();
}

export function openLabelImportDialog({ projectId, onDone }) {
  const input = el("input", { class: "input", id: "labels-path", type: "text", autocomplete: "off", placeholder: String.raw`D:\exports\my-dataset   or   D:\exports\labels.zip` });
  const problem = el("p", { class: "error-text", role: "alert" });
  const result = el("div", { class: "stack", role: "status" });
  let busy = false;
  let handle;

  const start = async () => {
    if (busy) return;
    busy = true;
    problem.textContent = "";
    result.replaceChildren();
    try {
      const r = await api(`/api/projects/${projectId}/label-imports`, { method: "POST", body: { path: input.value.trim() } });
      const lines = [`${r.format.toUpperCase()}: ${plural(r.annotations_imported, "annotation")} on ${plural(r.matched_images, "image")}.`];
      if (r.classes_created.length) lines.push(`New classes: ${r.classes_created.join(", ")}.`);
      if (r.unmatched_images.length) lines.push(`${plural(r.unmatched_images.length, "image")} in the file are not in this project (for example ${r.unmatched_images.slice(0, 3).join(", ")}).`);
      if (r.skipped.length) lines.push(`${plural(r.skipped.length, "item")} skipped (for example: ${r.skipped.slice(0, 2).join("; ")}).`);
      if (r.failed_images.length) lines.push(`${plural(r.failed_images.length, "image")} could not be saved: ${r.failed_images.slice(0, 2).join("; ")}.`);
      result.replaceChildren(...lines.map((text) => el("p", { text })));
      toast(`Imported ${plural(r.annotations_imported, "annotation")}`);
      if (onDone) await onDone(r);
    } catch (error) {
      problem.textContent = error.message;
    } finally {
      busy = false;
    }
  };

  input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); start(); } });
  handle = openDialog({
    title: "Import labels",
    body: [
      el("div", { class: "field" }, el("label", { for: "labels-path", text: "Folder or .zip with COCO or YOLO labels" }), input,
        el("span", { class: "hint", text: "Images are matched by file name and must already be in this project. Their annotations are replaced by the imported ones. Missing classes are created." })),
      problem,
      result,
    ],
    actions: [
      { label: "Close", onClick: (close) => close("done") },
      { label: "Import labels", primary: true, onClick: start },
    ],
  });
  input.focus();
  return handle;
}
