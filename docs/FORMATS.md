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
- **[U]** Visibility values: the Ultralytics pose page (read 2026-11-19) says the flag is "optional but useful for datasets that annotate occlusion" and `kpt_shape: [n, 2|3]` gives the dims, but it does NOT define the values. 0 / 1 / 2 as in COCO remains a convention; still unverified. Also: the segment page (community reply) says each row is one polygon, so holes cannot be separate rows.
- **[V]** Classification layout (<https://docs.ultralytics.com/datasets/classify/>, 2026-11-19): `train/` and `val/` required, `test/` optional; each contains one sub-folder per class holding the images.

## 3. COCO
Source to verify: <https://cocodataset.org/#format-data> (page did not render in our fetcher; use the site in a browser or a mirror of the spec).
- **[U]** (page <https://cocodataset.org/#format-data> still does not render in our fetcher on 2026-11-19; partly confirmed from `pycocotools/coco.py`, see below) One JSON per split with `images[]` (`id`, `file_name`, `width`, `height`), `annotations[]` (`id`, `image_id`, `category_id`, `bbox [x, y, w, h]` in pixels from top-left, `area`, `iscrowd`, `segmentation`), `categories[]` (`id`, `name`, `supercategory`).
- **[V]** `segmentation` (from `pycocotools/coco.py` `annToRLE`, 2026-11-19): a list is a polygon set (several parts may form one object); a dict with list `counts` is uncompressed RLE; otherwise compressed RLE.
- **[V]** Skeleton edges are 1-based (`pycocotools` subtracts 1: "turn skeleton into zero-based index"). **[U]** `keypoints [x, y, v, …]`, `num_keypoints` and visibility 0/1/2 are not stated in the code we read; confirm on the official page.
- **[V]** CVAT lists "COCO 1.0" (boxes, oriented boxes, polygons, masks) and "COCO Keypoints 1.0" (skeletons) as separate formats.
- **[V]** Label Studio's COCO export covers Brush, Rectangle, KeyPoint and Polygon labels; keypoints need a parent rectangle.

## 4. CVAT
Source: <https://docs.cvat.ai/docs/dataset_management/formats/> (**[V]** list below).
- Formats incl.: COCO 1.0, COCO Keypoints 1.0, CVAT for images 1.1, CVAT for video 1.1, Datumaro 1.0, Pascal VOC 1.1, YOLO 1.1 (boxes), Ultralytics YOLO Detection / Segmentation / Pose / Classification / OBB, LabelMe 3.0, KITTI, Cityscapes, and others.
- Shapes in "CVAT for images 1.1": tags, boxes, oriented boxes, polygons, polylines, points, cuboids, skeletons, ellipses, masks.
- **[V]** "CVAT for images 1.1" (<https://docs.cvat.ai/docs/dataset_management/formats/format-cvat/>, 2026-11-19): root `<annotations>` with `<version>1.1`, `<meta>`, then one `<image id name width height>` per image. Children: `<box label xtl ytl xbr ybr occluded z_order>`; `<polygon|polyline|points label points occluded z_order>` with `points` = `x,y;x,y;…`; `<tag label source>`; `<skeleton label z_order>` holding `<points label occluded outside points>`; `<mask … rle left top width height>`; custom `<attribute name="…">value</attribute>`. The page's full XML templates were not in the fetched text.
- **Built 2026-11-19 (`studio/formats/cvat.py`):** "CVAT for images 1.1" boxes and polygons, export and import. Keypoints are not written (CVAT needs a skeleton definition whose XML we did not verify) and are counted as left out; on import `<points>`, `<polyline>`, `<skeleton>`, `<mask>`, `<tag>`, rotated boxes etc. are listed in the report by type. Files with a DOCTYPE/ENTITY are refused. Not tested against a real CVAT server.
- **Adapter strategy (decision):** prefer CVAT's COCO 1.0 / COCO Keypoints 1.0 and Ultralytics YOLO exports as the interchange path (formats we already support); add "CVAT for images 1.1" only if needed for shapes COCO cannot carry.
- **[V]** CVAT licence: MIT (`LICENSE` on `develop`, read 2026-11-19; Intel + CVAT.ai copyright).

## 5. Label Studio
Source: <https://labelstud.io/guide/export> (**[V]** unless noted).
- Export formats: JSON (full), JSON_MIN, CSV/TSV, COCO, YOLO (boxes and keypoints), Pascal VOC XML, brush-label NumPy/PNG.
- Native JSON: tasks with `id`, `data` (e.g. image URL), `annotations[]` (each with `result[]`, `was_cancelled`, `ground_truth`, `completed_by`, timestamps, `lead_time`), `predictions[]` (adds `model_version`, optional `score`), `drafts[]` in snapshots only.
- Each `result` item: `id`, `type` (e.g. `rectanglelabels`), `from_name`, `to_name`, `value`; `parentID` links keypoints to their rectangle; examples include `original_width`, `original_height`, `image_rotation`.
- **Coordinates are percentages of the image size**: `pixel = value / 100 × original_dimension`. Rectangle `value`: `x, y, width, height, rotation, rectanglelabels[]`.
- **[V]** `polygonlabels` (<https://labelstud.io/tags/polygonlabels>, 2026-11-19): `value.points` = `[[x, y], …]` as percentages (0-100) of the image size, plus `value.polygonlabels: ["Car"]`; `original_width/height` in pixels. **[V]** `keypointlabels` value = `x, y, width, keypointlabels` (no height), `parentID` = the rectangle; coordinates are percentages. **[U]** what a keypoint's `width` means (our exporter must not depend on it).
- **[V]** Licence: Label Studio community repo is Apache-2.0 (`LICENSE` on `develop`, 2026-11-19). **[U]** the separate `label-studio-frontend` repo could not be read (GitHub API 403).
- **Built 2026-11-19 (`studio/formats/labelstudio.py`):** JSON tasks with `rectanglelabels`, `polygonlabels` and `keypointlabels` (+ `parentID` to a parent rectangle = the class), percentages, plus a matching `labeling_config.xml`. Known losses (reported): no visibility flag, so hidden points return visible; only labelled points travel, so an imported class gets a skeleton of just those names; rotated rectangles skipped. Image references are matched by base file name, also after stripping an 8-hex upload prefix (**[U]** this prefix behaviour is from memory, not a page). The keypoint `width` is written as 0.3 and never read. Not tested against a real Label Studio.
- **Adapter strategy (decision):** import/export Label Studio JSON for boxes, polygons and keypoints; also accept its COCO/YOLO exports through our own COCO/YOLO importers.

## 6. Pascal VOC (secondary)
**[V]** supported by CVAT and Label Studio (boxes). **[U]** XML schema details. Not in v1 unless asked.

## 7. Verification to-do (before Stage 3)
- Note 2026-11-13: Stage 3.1 code follows the COCO / YOLO layouts described above and is covered by our own golden and round-trip tests; no third-party loader has read our files yet.
- [ ] Remaining **[U]** after the 2026-11-19 pass: YOLO pose visibility values; COCO official field list, `num_keypoints` and keypoint visibility (needs the cocodataset.org page in a browser); Pascal VOC schema; frontend-library licence.
- [ ] Write one golden sample file per format and task type under `tests/data/formats/` (tiny, synthetic, no real datasets).
- [x] Licences checked 2026-11-19: CVAT MIT, Label Studio Apache-2.0, `supervision` MIT (`LICENSE.md`). [ ] Label Studio frontend library still unchecked.
