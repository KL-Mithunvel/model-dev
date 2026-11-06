# FORMATS — dataset format summaries (Gate G1)

Neutral storage targets: **COCO** and **YOLO**. Adapters: **CVAT** and **Label Studio**. Read 2026-11-06. Each item is tagged:
- **[V]** verified against the cited public page this session.
- **[U]** unverified — written from general knowledge or the page was incomplete. **Must be checked against the official spec before Stage 3 code**, and the tag changed to [V] with the source.

## 1. Our internal model (decision)
Store annotations in SQLite in **pixel coordinates, origin top-left**, per image: `bbox (x, y, w, h)`, `polygon [(x, y)…]`, `keypoints [(x, y, v)…]`, class id. Convert at the boundary. Rationale: pixel space is lossless and independent of any format's normalisation. Round-trip tests (export → import) are mandatory per format and task type (PLAN Stage 3).

## 2. YOLO (Ultralytics-style text labels)
Source: <https://docs.ultralytics.com/datasets/detect/>, `/segment/`, `/pose/`. (The format is a de-facto standard; using it does not involve importing the AGPL Ultralytics package.)
- **[V] Layout:** parallel `images/` and `labels/` directories per split; one `.txt` per image with the same base name; the label path is found by swapping the last `/images/` for `/labels/`. Images with no objects need no `.txt`.
- **[V] Dataset YAML:** `path`, `train`, `val`, optional `test` (directory, file, list, or `.txt` of paths), `names` (index → name), optional `download`.
- **[V] Detection line:** `class x_center y_center width height`, all normalised 0–1 by image width/height; class index is zero-based.
- **[V] Segmentation line:** `class x1 y1 x2 y2 … xn yn`, normalised; at least 3 points; variable length per row.
- **[V] Pose line:** `class x y w h px1 py1 [v1] px2 py2 [v2] …`, normalised; visibility is optional per file and its allowed values are not defined on the page. YAML keys `kpt_shape: [n, 2|3]` and optional `flip_idx`.
- **[U]** Visibility values in practice are 0 = not labelled, 1 = labelled but occluded, 2 = visible (same as COCO). Confirm.
- **[U]** Classification layout (folders per class) — confirm before implementing.

## 3. COCO
Source to verify: <https://cocodataset.org/#format-data> (page did not render in our fetcher; use the site in a browser or a mirror of the spec).
- **[U]** One JSON per split with `images[]` (`id`, `file_name`, `width`, `height`), `annotations[]` (`id`, `image_id`, `category_id`, `bbox [x, y, w, h]` in pixels from top-left, `area`, `iscrowd`, `segmentation`), `categories[]` (`id`, `name`, `supercategory`).
- **[U]** `segmentation`: list of polygons `[[x1, y1, x2, y2, …]]` for `iscrowd = 0`; RLE dict for `iscrowd = 1`.
- **[U]** Keypoints: `keypoints [x1, y1, v1, …]`, `num_keypoints`; category carries `keypoints` (names) and `skeleton` (edges, 1-based). Visibility 0/1/2.
- **[V]** CVAT lists "COCO 1.0" (boxes, oriented boxes, polygons, masks) and "COCO Keypoints 1.0" (skeletons) as separate formats.
- **[V]** Label Studio's COCO export covers Brush, Rectangle, KeyPoint and Polygon labels; keypoints need a parent rectangle.

## 4. CVAT
Source: <https://docs.cvat.ai/docs/dataset_management/formats/> (**[V]** list below).
- Formats incl.: COCO 1.0, COCO Keypoints 1.0, CVAT for images 1.1, CVAT for video 1.1, Datumaro 1.0, Pascal VOC 1.1, YOLO 1.1 (boxes), Ultralytics YOLO Detection / Segmentation / Pose / Classification / OBB, LabelMe 3.0, KITTI, Cityscapes, and others.
- Shapes in "CVAT for images 1.1": tags, boxes, oriented boxes, polygons, polylines, points, cuboids, skeletons, ellipses, masks.
- **[U]** The XML structure of "CVAT for images 1.1" (`<annotations><image …><box|polygon|points|skeleton …>`) was not on the fetched page. Verify from CVAT's format page before writing the adapter.
- **Adapter strategy (decision):** prefer CVAT's COCO 1.0 / COCO Keypoints 1.0 and Ultralytics YOLO exports as the interchange path (formats we already support); add "CVAT for images 1.1" only if needed for shapes COCO cannot carry.
- **[U]** CVAT licence: believed MIT for the core; confirm from its repository before documenting.

## 5. Label Studio
Source: <https://labelstud.io/guide/export> (**[V]** unless noted).
- Export formats: JSON (full), JSON_MIN, CSV/TSV, COCO, YOLO (boxes and keypoints), Pascal VOC XML, brush-label NumPy/PNG.
- Native JSON: tasks with `id`, `data` (e.g. image URL), `annotations[]` (each with `result[]`, `was_cancelled`, `ground_truth`, `completed_by`, timestamps, `lead_time`), `predictions[]` (adds `model_version`, optional `score`), `drafts[]` in snapshots only.
- Each `result` item: `id`, `type` (e.g. `rectanglelabels`), `from_name`, `to_name`, `value`; `parentID` links keypoints to their rectangle; examples include `original_width`, `original_height`, `image_rotation`.
- **Coordinates are percentages of the image size**: `pixel = value / 100 × original_dimension`. Rectangle `value`: `x, y, width, height, rotation, rectanglelabels[]`.
- **[U]** `polygonlabels` value structure (believed `points: [[x%, y%], …]`) and keypoint `width` meaning — not documented on the fetched page. Verify.
- **[U]** Licence: believed Apache-2.0 for the community edition and its frontend library; confirm.
- **Adapter strategy (decision):** import/export Label Studio JSON for boxes, polygons and keypoints; also accept its COCO/YOLO exports through our own COCO/YOLO importers.

## 6. Pascal VOC (secondary)
**[V]** supported by CVAT and Label Studio (boxes). **[U]** XML schema details. Not in v1 unless asked.

## 7. Verification to-do (before Stage 3)
- [ ] Confirm every **[U]** line above against the official spec and update this file with the source and date.
- [ ] Write one golden sample file per format and task type under `tests/data/formats/` (tiny, synthetic, no real datasets).
- [ ] Check licences: CVAT, Label Studio (and its frontend library), `supervision`.
