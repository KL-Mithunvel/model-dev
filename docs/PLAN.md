# PLAN — Local Vision Studio (working title)

A local, offline, privacy-first alternative to a hosted computer-vision platform: import images, create projects, annotate (with AI help), train models, and watch the hardware while it runs. Open-source app; user datasets are never committed.

Status: **plan approved in outline 2026-11-06; no application code written yet.** Update this file in the same commit as any change of scope.

## 1. Decisions (source: owner answers, 2026-11-06)
| Topic | Decision |
|-------|----------|
| Repo | Lives on `main` of `model-dev`; `.CLAUDE/CLAUDE.md` Branch Policy updated accordingly |
| Users | Single user, no login in v1 |
| Data | Images only. Up to a few thousand per dataset. SQLite + files on disk |
| Tasks | Object detection, classification, segmentation, keypoints |
| Annotation | Built in-house (canvas, vanilla JS). Neutral storage: COCO / YOLO. Import/export adapters for CVAT and Label Studio |
| AI-assist | ML-backend protocol; backends: SAM click-to-segment, zero-shot text prompts, active learning (own model) |
| Weights | One-time download from the internet, cached, then offline. Dataset images never leave the machine |
| Models | Permissive first (RF-DETR, RT-DETR, torchvision). Ultralytics YOLO (AGPL) only as an optional, clearly separated plugin |
| Export | PyTorch, ONNX, TFLite, TensorRT |
| Monitor | CPU/RAM/disk, NVIDIA GPU (NVML), Intel Arc/NPU best-effort, training metrics alongside, history stored per run |
| Sharing | Remote training workers on the owner's other machines |
| UX | Apple HIG principles — see `docs/UX.md` |
| Roboflow study | Clean-room: public docs, API reference, open-source repos, own-account behaviour. See `docs/REA.md` |
| Multi-agent process | Agreed 2026-11-06 — `docs/AGENTS.md` |
| Licence | Core under a permissive licence (to be chosen in Stage 9). YOLO plugin kept separate |

## 2. Target machine (survey 2026-11-06)
Dell Precision 3591 · Core Ultra 7 155H (16C/22T) · 31.5 GB RAM · RTX 1000 Ada 6 GB VRAM (driver 596.71, CC 8.9) · Intel Arc iGPU/NPU · Windows 11 · Python 3.13.7 · torch not installed. Hardware is read at runtime, never hard-coded. A larger "bigger CPU" machine exists (details unknown — see Open Items).

## 3. Architecture (target)
```
Browser UI (vanilla JS, tokens.css)  <──HTTP/WebSocket──>  FastAPI backend (studio/api)
                                                            ├─ core: projects, datasets, images, labels (SQLite + files)
                                                            ├─ formats: COCO / YOLO / CVAT / Label Studio adapters
                                                            ├─ mlbackend: protocol client + built-in backends (SAM, zero-shot, own model)
                                                            ├─ train: Trainer interface → RF-DETR / RT-DETR / torchvision / YOLO plugin
                                                            ├─ monitor: psutil + NVML + Intel sampler → ring buffer → SQLite per run
                                                            └─ workers: job queue ⇄ remote worker agents
```
- Backend-heavy, thin frontend (owner preference). Long tasks run in worker processes, not request handlers.
- Every tunable lives in `config.yaml`. Secrets only in gitignored `.env`.
- Repo layout: `studio/` (package; `studio/web/` for the UI), `tests/`, `tools/`, `docs/`, `data/` (gitignored), `config.yaml`, `requirements.txt`.

## 4. Preflight gates
| Gate | Why it exists | To clear (record in `CLAUDE-LOG.md`) |
|------|---------------|---------------------------------------|
| G1 Understand existing state | Building against a guessed spec wastes stages | Clean-room notes on the reference platform's feature set from allowed sources (`docs/FEATURES.md`); COCO/YOLO/CVAT/Label Studio format specs summarised with versions |
| G2 Survey environment | A CPU-only torch wheel silently ignores the GPU | `tools/compute_survey.py` output recorded (done); CUDA torch installs and `torch.cuda.is_available()` is true on Python 3.13, else fall back to a 3.12 venv and record why |
| G3 Confirm where it runs | Export formats and worker design depend on targets | Owner confirms OS/GPU of worker machines, whether any machine has no internet, and export targets actually needed |

No code covered by a gate is written until the gate is cleared.

## 5. Versioning and process
- Small tagged versions, one deliverable each (`v0.0` … `v1.0`). A version is tagged only when its tests pass and its docs are updated in the same commit.
- Commit at each good step (owner request: do not lose progress). Commit messages: imperative, ≤ 72 chars, with the `Co-authored-by` trailers.
- Each stage's **success criteria** include tests (`pytest`) and **UX criteria** (the checklist in `docs/UX.md`).
- Multi-agent roles, worktrees, QA gate and merge rules: agreed 2026-11-06, see `docs/AGENTS.md`. Default is builder + independent reviewer; owner approves each stage plan and every tag.

## 6. Stages

### Stage 0 — Foundations (v0.0)
Goal: a clean, documented base and cleared gates.
- **0.1 Docs and policy** — Update `.CLAUDE/CLAUDE.md` (Project Overview, Branch Policy, Rules); add `docs/PLAN.md`, `docs/UX.md`, `docs/REA.md`. *Done in this commit series.*
- **0.2 Reference notes (G1)** — Write `docs/FEATURES.md`: what the reference platform does (projects, datasets, versions, annotation, training, deploy), from allowed sources only. Write `docs/FORMATS.md`: COCO, YOLO, CVAT XML/JSON, Label Studio JSON.
  Success: each feature has a source link and a one-line "our approach"; no copied text beyond short quotes.
- **0.3 Environment (G2)** — Create venv, `requirements.txt`, install CUDA torch, verify GPU. Add `config.yaml`, `.env.example`, `tools/` checks, `pytest` skeleton, ruff config.
  Files: `config.yaml`, `requirements.txt`, `.env.example`, `tests/test_smoke.py`, `pyproject.toml`.
  Success: `pytest` passes; `python tools/compute_survey.py` shows torch + CUDA.
- **0.4 Where it runs (G3)** — Ask the owner about worker machines and export targets; record answers.
  `v0.0` was tagged 2026-11-06 with G1 and G2 cleared and **G3 deferred by the owner**. G3 must be answered before Stage 6 (training backends/export) and Stage 8 (workers) design starts.

### Stage 1 — Data core and app shell (v0.1)
Goal: create a project, import images, see them in a gallery.
- **1.1 Schema and storage** — SQLite schema (projects, datasets, images, classes, annotations, splits, runs), migrations, file layout under `data/<project>/`, path helper.
- **1.2 Import** — Folder and zip import, content hashing (duplicate detection), EXIF-aware thumbnails, corrupt-file report.
- **1.3 API** — FastAPI routes for projects/datasets/images; pagination; WebSocket for job progress.
- **1.4 App shell (UX)** — Sidebar/toolbar/inspector layout, `tokens.css`, light/dark, empty states, shortcut sheet, command palette.
- **1.5 Gallery and splits** — Thumbnail grid with keyboard selection, filters, train/val/test split tool.
  Success: import 2,000 images in under a minute on this machine; gallery scrolls smoothly; duplicates skipped and reported; all UX checklist items pass.

  **Independent review (2026-11-06): first verdict FAIL** — 1 blocker (the skip link replaced the page with "Page not found"), plus 10 should-fix items (zip edge cases, batch accounting after unexpected errors, delete-during-import, SQLite variable limit, router race, lost keyboard focus, Space handling, stale tag filter, no import cancel, docs-in-same-commit). All were fixed or recorded as debt in `.CLAUDE/CLAUDE.md`; the fixes were verified with 84 pytest tests (up from 60) and 15 real-browser checks (`tools/ui_smoke.py`, all passing). **Import cancel is now implemented**, so the "cannot be cancelled" deviation below no longer applies. A second review pass has not been run.
  **Built 2026-11-06; tagged `v0.1` on 2026-11-07 (commit 39f055f).** Measured: 2,000 synthetic 1024×768 JPEGs imported in 55.8 s (36 img/s; re-import of the same set, all duplicates, 2.5 s). 60 tests pass; ruff clean; contrast ratios checked for both themes (all ≥ 4.5:1 text, ≥ 3:1 UI). Behaviour verified in headless Edge through a DevTools script (selection, keyboard navigation, split + undo, import with duplicates/corrupt/ignored files, palette, shortcut sheet, light/dark, narrow layout).
  **Deviations from the plan above (owner approved the design choices of copy-not-reference and folder path, not these):**
  - No separate "datasets" table: a project holds images directly; immutable versions arrive in Stage 3.
  - Gallery filters are split, tag, name search (and batch via API) instead of "duplicate": duplicates are never stored, they are counted on the batch report.
  - Split assignment is random, not stratified (no labels yet).
  - ~~Imports cannot be cancelled yet~~ — fixed after review (cooperative cancel, kept partial results).

### Stage 2 — Annotation (v0.2–v0.4)
Goal: a fast, forgiving annotator.
**Approved by the owner 2026-11-07** with these decisions: classification is **single-label** (one class per image, `images.label_class_id`); "no objects" is an **explicit action** (`images.marked_empty`); key map as below. Agent model A; an independent review runs before each tag and **the owner approves each tag**.

**Design decisions**
| Topic | Decision |
|-------|----------|
| Coordinates | Pixels on the EXIF-oriented image, origin top-left (matches `images.width/height`) |
| Drawing surface | SVG overlay on the image inside a zoom/pan container (handles are real elements) |
| Saving | Autosave with replace-all `PUT /api/images/{id}/annotations` carrying a revision number (409 on conflict). A synchronous `localStorage` draft is written on every edit and cleared after a successful save, so a killed tab loses nothing |
| Undo/redo | Client-side history of immutable snapshots (pure JS module, unit-tested with `node --test`) |
| "Labelled" | An image is labelled if it has ≥ 1 annotation, **or** is marked "no objects", **or** has an image label |
| Classes | Per project: name (unique, case-insensitive), colour from a colour-blind-safe palette in `config.yaml`, optional skeleton (v0.4). One class can be used for boxes and polygons |
| Validation | Server validates every annotation (bounds, minimum size, class belongs to project, kind-specific shape); box, polygon and keypoint validators exist from v0.2 so v0.3/v0.4 only add UI |

**Key map**: tools `V` select · `B` box · `P` polygon (v0.3) · `K` keypoint (v0.4) · `H` pan (or hold Space and drag) · wheel zoom · `0` fit · `+`/`−` zoom · `A`/`D` previous/next image · `N` next unlabelled · `E` toggle "no objects" · `1`–`9` active class (or class of the selection) · `Shift+1`–`9` image label · arrows nudge (Shift ×10) · Alt+arrows resize · `Delete` · `Ctrl+D` duplicate · `Ctrl+Z` / `Ctrl+Shift+Z` (or `Ctrl+Y`) · `Esc` cancel/deselect · `Enter` in the box tool drops a default box at the view centre (keyboard-only drawing) · `Tab` inside the image area cycles annotations (and leaves the area after the last one, so keyboard users are never trapped).

- **2.1 Backend (v0.2)** — migration `002_annotations.sql` (`classes`, `annotations`, `images.marked_empty`, `images.label_class_id`, `images.annotations_rev`); `studio/annotations.py` (pure validation); repo + API: classes CRUD (delete of a used class needs `force`), image annotations GET/PUT with revision check, project annotation stats, neighbours endpoint (prev/next/next-unlabelled), gallery filters (labelled/unlabelled, class) and per-image counts.
- **2.2 Annotator shell (v0.2)** — route `#/projects/:id/annotate/:imageId`; tool strip, stage with zoom/pan, inspector (image label, classes, annotation list), filmstrip, save indicator, saver with debounce/queue/draft recovery; pure modules `geometry.js`, `history.js`, `editor.js`, `saver.js`.
- **2.3 Box tool and editing (v0.2)** — draw, move, resize (8 handles), delete, duplicate, nudge, class change, unlimited undo/redo, keyboard-only drawing.
- **2.4 Flow (v0.2)** — "no objects", next unlabelled, "repeat previous image's boxes", progress bar, gallery badges/filters and "Annotate" entry points.
- **2.5 Polygons (v0.3)** — click to add vertices, close on first point/Enter, move/add/delete vertices, simplify.
- **2.6 Keypoints (v0.4)** — skeleton editor per class, sequential placement with visibility (0 not labelled, 1 hidden, 2 visible), drag points, copy skeleton from previous image.

**Success criteria**: 20 boxes drawn with no menu trips; undo/redo through 100 steps restores the exact state; no data loss when the tab is killed right after an edit; keyboard-only annotation works; pan/zoom stays smooth with 200 annotations (measured, provisional); EXIF-rotated images line up (browser check); all of `docs/UX.md` §9; `pytest`, `node --test`, and `tools/dev_run.py` scenarios (real mouse drawing, undo, reload persistence) pass; independent review before each tag.

### Stage 3 — Formats and versions (v0.5)
Goal: no lock-in; reproducible datasets.
- **3.1 COCO + YOLO** import/export for all four task types.
- **3.2 Adapters** — CVAT and Label Studio import/export.
- **3.3 Dataset versions** — Immutable snapshots (frozen image list, labels, split, preprocessing) with a manifest and hash.
  Success: round-trip tests (export → import → identical annotations) for every format and task type; snapshot hash is stable.

### Stage 4 — AI-assist (v0.6)
Goal: speed up labelling without sending data anywhere.
- **4.1 ML-backend protocol** — Define request/response schema (images in, predictions out), health check, versioning, local-only by default. Document in `docs/ML_BACKEND.md`.
- **4.2 SAM backend** — Click-to-segment with box/polygon result; weights downloaded on request.
- **4.3 Zero-shot backend** — Text prompt → boxes (Grounding DINO or OWLv2, chosen after a licence/VRAM check).
- **4.4 Review UX** — Predictions appear as dashed "suggestions"; accept, edit or reject individually or in bulk; confidence filter.
  Success: protocol contract tests pass with a fake backend; SAM click returns a mask in under 2 s on the RTX; nothing is saved without user acceptance; fits in 6 GB VRAM.

### Stage 5 — Hardware monitor (v0.7)
Goal: see what the machine is doing, live and historically.
- **5.1 Samplers** — psutil (CPU per core, RAM, disk I/O), NVML (util, VRAM, temp, power, clocks), Intel best-effort (Windows performance counters), each behind a common interface with graceful "unavailable".
- **5.2 Storage** — Ring buffer in memory, down-sampled history per run in SQLite.
- **5.3 Dashboard** — Live charts on a shared time axis, units shown, specific warnings with one-click fixes.
  Success: sampling overhead under 2 % CPU; fake-sampler tests; dashboard works with no GPU present.

### Stage 6 — Training (v0.8–v0.9)
Goal: train from a dataset version and supervise it.
- **6.1 Trainer interface (v0.8)** — `fit`, `evaluate`, `export`, `resume`; config via YAML; deterministic seeds; checkpoints.
- **6.2 Backends** — RF-DETR, RT-DETR, torchvision; device picker (CUDA/CPU); VRAM estimate and auto batch-size suggestion for 6 GB.
- **6.3 Runs** — Run table, live loss/metric stream into the monitor screen, pause/cancel/resume, comparison view.
- **6.4 YOLO plugin (v0.9)** — Separate optional package with its own licence notice; core never imports it.
  Success: a small dataset trains end to end on GPU and on CPU; cancel is clean; resume reproduces the metric curve within tolerance; the core runs with the plugin uninstalled.

### Stage 7 — Evaluate, export, active learning (v0.10)
- **7.1 Evaluation** — mAP, per-class precision/recall, confusion matrix, worst-prediction browser.
- **7.2 Export** — PyTorch, ONNX (validated against PyTorch outputs), TFLite and TensorRT (each gated by a platform check; WSL route documented if needed).
- **7.3 Active learning** — Trained model becomes an ML backend that pre-labels the next batch; uncertainty sampling suggests what to label next.
  Success: ONNX output matches PyTorch within tolerance; failed exports explain themselves; active-learning loop runs on a toy dataset.

### Stage 8 — Remote workers (v0.11)
- **8.1 Job queue** — Persistent jobs with states and retries.
- **8.2 Worker agent** — Small process on another machine that pulls jobs, syncs the dataset version, trains, streams metrics, returns weights.
- **8.3 Security** — Pairing token, LAN-only by default, TLS option, dataset transfer limited to the chosen version.
  Success: a job runs on a second machine and its metrics appear in the monitor; unpaired workers are refused; network drop mid-job is recovered or reported.

### Stage 9 — Hardening and release (v1.0)
- Licence choice and notices, YOLO plugin licence boundary check, dependency pins with reasons, packaging (`pip install` / launcher), user guide, screenshot-free first-run tutorial, data-leak check (no dataset or secrets in git history), accessibility audit, performance pass.
  Success: clean install on a fresh machine works from the README; full UX checklist passes on every screen.

## 7. Risks
| Risk | Mitigation |
|------|------------|
| Python 3.13 vs torch/CUDA wheels | Gate G2; fall back to 3.12 venv |
| 6 GB VRAM limits | Small models, auto batch size, clear warnings, remote workers |
| TensorRT/TFLite on Windows | Platform checks, WSL documentation, ONNX as the guaranteed export |
| Annotator polish takes longer than planned | Stage 2 split into three small versions; adapters allow using CVAT/Label Studio meanwhile |
| AGPL contamination from YOLO | Optional plugin, separate package, never imported by core |
| Weights licences differ (SAM, Grounding DINO, OWLv2) | Licence check recorded per weight before it is added |
| Data privacy | `data/` gitignored; no telemetry; network only for weight downloads and paired workers |

## 8. Open items
- Worker machines: OS, GPU, network (G3).
- Which export targets are actually needed first.
- Project name and final licence.
- ~~Multi-agent roles and merge rules~~ — resolved, `docs/AGENTS.md`.
- Accent colour / density preference for the UI.
