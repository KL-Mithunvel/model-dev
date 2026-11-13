# CLAUDE.md

> **IMPORTANT:** Read `CLAUDE-COMMON.md` first — it contains general must-follow instructions (companion files, deployment model, workflow, template structure). This file contains repo-specific instructions. Anything here overrides `CLAUDE-COMMON.md`.
>
> **Also read `PROJ_STARTER.md`** — it contains the owner's personal preferences (interaction rules, coding standards, tech stack choices, commit style). Copy its sections into any new project's `CLAUDE.md` User Rules alongside the rules from `CLAUDE-COMMON.md`.

---

## ⚠ Branch Policy — these branches are never merged

> **Repo-specific — do not copy this section into new projects.**

This repo holds **two independent copies** of the template, kept as separate branches for the owner's personal use:

| Branch | Content |
|--------|---------|
| `main` | The template library **and, since 2026-11-06, the Local Vision Studio app** (owner decision: no separate repo) |
| `machine-vision` | The same template plus the machine-vision baseline — four gates, docs, tools, Roboflow skills |

- **Never merge, rebase, or open a PR between `main` and `machine-vision`, in either direction.** They are meant to diverge. `machine-vision` is a personal copy, not a feature branch.
- **Do not treat `machine-vision` as unmerged work.** Do not suggest merging it, syncing it, or resolving differences between the two branches.
- **To share an improvement, copy the text by hand** into the other branch's files, as its own commit on that branch, and only after asking the owner.
- **Check `git branch --show-current` before editing.** Changes belong to the branch you are on.
- **App on `main` (owner decision, 2026-11-06):** the app code (`studio/`, `tests/`, `config.yaml`) and its docs (`docs/`) live on `main` beside the template files. The generic template files under `.CLAUDE/` stay generic: when copying them to another project, leave out the app-specific sections (Project Overview, Preflight Gates, Development Rules, Project-Specific Overrides below).

---

## About This Repository

This repo is a curated library of `CLAUDE.md` files. Each file serves as a project brief for AI-assisted development sessions — capturing architecture, rules, conventions, and status so that Claude Code can contribute effectively without needing to re-discover project context from scratch.

The files here are used as **standard templates and reference material** for future projects.

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Project template — copy this into new projects |
| `CLAUDE-COMMON.md` | Universal workflow rules — must-follow for every project |
| `PROJ_STARTER.md` | Personal preferences and tech stack defaults — copy into new projects |
| `<project-id>.md` | `<Project name — one-line description>` |

New entries follow the same naming convention: `<short-project-id>.md`.

---

## How to Start a New Project

1. Copy `CLAUDE.md` into the new project root (keep the name `CLAUDE.md`).
2. Copy `CLAUDE-COMMON.md` and `PROJ_STARTER.md` alongside it, or reference the ones in this library.
3. Fill in every `[TO BE FILLED]` section below with the project's actual details.
4. In the **User Rules** section: copy `CLAUDE-COMMON.md` → Standard User Rules verbatim, then copy `PROJ_STARTER.md` contents below that. Add project-specific overrides last, clearly labelled.
5. Delete any `[if applicable]` sections that do not apply to the project.

---

## Project Overview

**Local Vision Studio** (working title) — a local, offline, privacy-first alternative to a hosted computer-vision platform: import images, create projects, annotate (with AI assistance), train models, and monitor CPU/GPU hardware live. Author: kl mithunvel. Open-source app; user datasets are never committed. Licence: to be chosen in Stage 9 (core permissive; optional Ultralytics YOLO plugin kept separate because it is AGPL).

- **Full plan, decisions, stages, gates and risks:** `docs/PLAN.md` (read first).
- **UX rules (Apple HIG principles, tokens, checklist):** `docs/UX.md`.
- **Third-party REA tool and the clean-room rule:** `docs/REA.md`.
- **Status:** planning complete in outline; no application code yet (Stage 0 in progress).
- **Stack:** Python (FastAPI, SQLite, PyTorch) backend; thin vanilla-JS frontend; YAML config. Entry point (planned): `python -m studio`. Runtime: Python 3.13 (fallback 3.12 if CUDA torch wheels require it — see Gate G2).

---

## Preflight Gates

No application code is written until these are cleared and recorded in `.CLAUDE/CLAUDE-LOG.md`. Details are in `docs/PLAN.md` §4.

1. **G1 Understand existing state** — clean-room feature notes (`docs/FEATURES.md`) and format summaries (`docs/FORMATS.md`) from allowed sources only. *Why: building against a guessed spec wastes stages.*
2. **G2 Survey environment** — `tools/compute_survey.py` recorded (done 2026-11-06); CUDA torch verified. *Why: a CPU-only torch wheel silently ignores the GPU.*
3. **G3 Confirm where it runs** — owner confirms worker machines (OS, GPU, network) and needed export targets. *Why: export formats and worker design depend on them.*

---

## Running the System

Windows (PowerShell), from the repo root. The venv lives in `venv/` (gitignored).

```powershell
# One-time setup (CUDA torch must come from the CUDA index — Gate G2)
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu130

# Every session
venv\Scripts\activate

# Check / test
python -m py_compile studio\*.py
python -m ruff check .
python -m pytest -q                 # GPU-marked tests skip themselves when no CUDA GPU is present
python tools\compute_survey.py      # CPU / RAM / disk / GPU survey
```

### Run the app in a real browser and drive it like a user (`tools/dev_run.py`)

```powershell
python tools\dev_run.py list                       # scenarios in tools\scenarios\
python tools\dev_run.py run smoke                  # VISIBLE Edge window, watchable pace (default)
python tools\dev_run.py run annotate_flow --headless   # also: annotate, annotate_gallery, annotate_robust, annotate_polygon, annotate_polygon_review, annotate_perf
python tools\dev_run.py run smoke --headless       # no window, full speed (quick checks / CI-style)
python tools\dev_run.py run tour --pace 1.5        # narrated demo, slower
python tools\dev_run.py open                       # app + demo data + browser for YOU; Ctrl+C stops all
```

- It starts the app on a free port with throwaway data (never `data/`), opens a browser with a throwaway profile (never your own Edge profile), and stops every process it started.
- Input is **real**: mouse moves along an eased path, clicks, double clicks, drags, wheel, keys and typing arrive as trusted events. The OS pointer itself cannot be moved; a red on-page cursor, click ripples and a narration banner show where the script is.
- It refuses to click an element a user could not click (covered by another element or zero-sized) and waits for the element to stop moving first. It re-finds elements every frame, because the app may re-render them.
- Needs Edge or Chrome (`STUDIO_BROWSER` or `--browser` to override). Screenshots of each run go to `data/dev_runs/` (gitignored, last 8 runs). Exit code 0 = all checks passed.
- Add a scenario: a file in `tools/scenarios/` with `DESCRIPTION`, optional `CONFIG` (config overrides), and `async def run(s)`; see `smoke.py`. API: `s.goto`, `s.click`, `s.drag`, `s.wheel`, `s.press("Ctrl+Z")`, `s.type_text`, `s.say`, `s.shot`, `s.check`, `s.wait_for`, `s.js`, `s.api`.
- `tools/ui_smoke.py` is a shim for `run smoke --headless`.

```powershell
python -m studio                    # http://127.0.0.1:8000 (host/port from config.yaml)
python -m studio --config other.yaml
```

Keep the server bound to `127.0.0.1`: it reads the folders you name in the import dialog, and its Host-header allowlist (`app.allowed_hosts`) is the DNS-rebinding guard.

---

## Architecture

Status: **v0.4 built** (v0.2 = boxes + classification, tagged; v0.3 adds polygons; v0.4 adds keypoints; v0.3 and v0.4 not yet tagged). Later stages: `docs/PLAN.md`.

| Path | Role |
|------|------|
| `studio/config.py` | Load `config.yaml` (`load_config`, `ConfigError`) |
| `studio/paths.py` | The only place data paths are built (`data_dir`, `db_path`, `project_dir`, `images_dir`, `thumbs_dir`) |
| `studio/db.py` | SQLite connect + forward-only migrations (`connect`, `migrate`, `utc_now`) |
| `studio/migrations/NNN_*.sql` | Schema, applied in order; version in `PRAGMA user_version` |
| `studio/repo.py` | SQL: projects, images, tags, splits, batches; `LABELLED_SQL` (what "labelled" means) |
| `studio/repo_annotations.py` | SQL: classes, annotations (replace-all save with revision lock), stats, neighbours |
| `studio/annotations.py` | Pure validation of box / polygon / keypoint annotations (`validate_annotation`, `validate_set`) |
| `studio/formats/{coco,yolo,geometry}.py` | **Pure** COCO and YOLO (detect/segment/pose) conversion, golden + round-trip tests in `tests/test_formats.py` |
| `studio/exporter.py`, `studio/label_import.py` | Project -> COCO/YOLO zip (`export_project`, dry run gives the report) and COCO/YOLO folder or zip -> annotations on matching images (`import_labels`) |
| `studio/importer.py` | Folder/zip import: hash, validate, EXIF, thumbnail, report |
| `studio/splits.py` | Pure train/val/test assignment (deterministic) |
| `studio/jobs.py` | One-worker in-process job runner with progress snapshots |
| `studio/api/app.py` | FastAPI app factory `create_app`; serves `studio/web/` |
| `studio/__main__.py` | `python -m studio` launcher |
| `tools/dev_run.py`, `tools/devbrowser.py`, `tools/scenarios/` | Dev tool: run the app in a real browser and drive/test it (see Running the System) |
| `studio/web/` | Vanilla-JS UI: `css/{tokens,app,annotator}.css`; shell `js/{main,ui,api,palette,limits,classes}.js`; views `js/views/{projects,gallery,annotate}.js` |
| `studio/web/js/{geometry,history,editor,saver}.js` | **Pure, unit-tested** annotator logic (no DOM): box/zoom math, undo history of frozen snapshots, immutable editing operations, autosave (debounce, local draft, retry, conflicts). Tests: `tests/js/*.test.mjs`, run by `node --test tests/js` and by `pytest` (`tests/test_js_units.py`) |

```
Browser (studio/web) --HTTP/WebSocket--> FastAPI (api/app.py) --> repo.py --> SQLite (data/studio.sqlite)
                                              |                      ^
                                              +--> jobs.py (1 worker thread) --> importer.py --> data/projects/<id>/{images,thumbs}
```

- **Concurrency:** request handlers are sync functions on FastAPI's thread pool, each with its own SQLite connection (`check_same_thread=False`, never shared). Imports run on the single job thread with their own connection, so writes from jobs never overlap. Job progress is in memory; durable results are in `batches`.
- **No simulation mode yet:** nothing in v0.1 touches hardware. Hardware samplers and ML backends will each ship with a fake (Development Rule 8).

---

## Key Modules

- **`importer.import_source(conn, config, project_id, source, progress=None) -> ImportReport`** — `source` is a folder or `.zip`. Raises `ImportFailed` (unknown project, missing/odd source, bad/oversized zip). Writes `data/projects/<id>/images/<sha256><ext>` (original bytes) and `thumbs/<sha256>.jpg`; inserts `images` rows; records a `batches` row. Zip members with path traversal or symlinks are skipped and reported. Outcomes per file are mutually exclusive: added / duplicate / corrupt / oversize / unsupported.
- **`splits.assign_splits(ids, ratios, seed) -> {id: split}`** — pure; largest-remainder counts; `validate_ratios` raises `ValueError`.
- **`repo.*`** — `create_project` (raises `ProjectExists`), `delete_project` (rows + files), `list_images(..., split, tag, batch_id, query)` → `(items, total)`, `set_tags`, `set_split`, `apply_splits` → `(counts, previous)` (the `previous` map powers Undo in the UI), `list_batches`. Functions commit before returning.
- **`api.app.create_app(config=None, allowed_hosts=None)`** — routes are listed in `/docs` when running. Errors are `{"detail": "<readable message>"}`.
- **`jobs.JobManager(keep_finished)`** — `submit(fn, kind, project_id=None) -> job_id` where `fn(progress, cancelled)`; `get`, `cancel(job_id)`, `has_active(project_id)`; a failing job never kills the worker; finished jobs are pruned. `POST /api/jobs/{id}/cancel` asks an import to stop before its next file; what was imported is kept and the report has `cancelled: true`. A project cannot be deleted while it has an active import (409).
- **Import robustness** — a bad zip member (clash, duplicate name, too long, encrypted) is reported and skipped; a per-file exception is counted as `corrupt` and the import continues; a database error aborts but the batch row keeps the counts so far; symlinks/junctions are not followed and are reported as ignored. `GET /api/limits` exposes name/tag/page limits so the UI never hard-codes them.
- **Frontend rules:** all text is inserted via `textContent`/`el()` (never `innerHTML`) because file names come from disk. Never pass `null` to `append`/`replaceChildren` (it prints "null"). Never rebuild a control the user is operating without restoring focus (`rebuild()` in `annotate.js` keys elements with `data-fk`). Never open a dialog on pointer-**down** (the release lands on it and steals focus); open it on release. The toast container AND the toast bodies are click-through (`pointer-events: none`; only the action and ✕ buttons take clicks) because toasts can cover the bottom of the canvas where users draw; at most 3 toasts are shown and every toast has a ✕.
- **Polygons (v0.3):** a polygon is `data.points = [[x, y], ...]` (>= 3 points, implicitly closed, hole-free). Drawn by clicking; closed by clicking the first point, Enter, or a double-click; Backspace / Ctrl+Z remove the last point while drawing; Esc cancels. When selected it shows corner handles (drag to move a point; Alt+click or Delete removes the selected point, never below 3) and small midpoint handles (drag to insert a point there: one undo step). Keyboard only: `P`, `Enter` drops a hexagon, `[` / `]` pick a point, arrows move it, `I` inserts after it. "Simplify polygon" runs Ramer-Douglas-Peucker with `annotations.simplify_epsilon_px` (never below 3 points; the toast has Undo). A polygon whose edges cross is allowed but flagged ("crosses itself" in the list and a toast); a polygon with (almost) zero area is refused by both browser and server (`min_polygon_area_px`). Pure logic: `geometry.js` (area, bounds, rigid move, point-in-polygon, nearest edge, self-intersection, simplify) and `editor.js` (`addPolygon`, `moveVertex`, `insertVertex`, `removeVertex`, `simplifyAnnotation`), tested in `tests/js/polygon.test.mjs`.
- **Keypoints (v0.4):** a class may have a skeleton `{names: [...], edges: [[i, j], ...]}` (`classes.skeleton`, validated by `annotations.validate_skeleton`, limits `annotations.max_keypoints` / `skeleton_name_max`). A keypoint annotation is `data.points = [[x, y, v], ...]`, one entry per skeleton name (the server checks the count); `v` 0 = not labelled (stored `0,0,0`), 1 = hidden, 2 = visible; at least one must be labelled. Once a class has keypoint annotations its number of points cannot change (renames and edge changes are fine). A class without a skeleton cannot hold keypoints (the save is refused); `skeleton: {}` is an error, `null` removes it; changing the point count is checked under the write lock (`BEGIN IMMEDIATE`). In the editor a keypoint set only takes a class with the same number of points (`editor.canTakeClass`; otherwise it keeps its class and a toast says why). Placement (`K`): click = visible, Shift+click = hidden, `X` skips, Backspace steps back, Enter finishes early, Esc cancels; the set finishes itself after the last point. Selected set: drag a point, drag the box to move all, `]`/`[` pick a point, arrows move it, `O` cycles visible/hidden/not labelled, Delete or Alt+click clears it, and the inspector lists every point with a state button. Keyboard-only: `K` then Enter drops a whole pose. The class dialog has the skeleton editor (`js/skeleton.js`: one name per line, connections as `a - b`, presets for a 17-point person and a 21-point hand). "Repeat previous image" copies keypoint sets too. Pure logic: `geometry.js` (keypoint section) and `editor.js` (`addKeypoints`, `placeKeypoint`, `setKeypointVisibility`), tested in `tests/js/keypoints.test.mjs` and `skeleton.test.mjs`; backend tests in `tests/test_keypoints_backend.py`.
- **Export / import of labels (Stage 3.1):** `GET /api/projects/{id}/export?format=coco|yolo&task=detect|segment|pose&images=true|false` returns a zip; `/export/preview` returns the same report without building it; `POST /api/projects/{id}/label-imports {path}` reads a COCO json (any `*.json` with `images` and `annotations` lists) or a YOLO dataset (`data.yaml` plus `labels/**/*.txt`) from a folder or zip. Only labelled images are exported (annotations, or marked "no objects" = empty label file); if any has a split, unassigned ones are left out and reported, otherwise all go to `train`. Import matches images by file name (YOLO: stem), REPLACES their annotations, creates missing classes (COCO keeps skeletons, YOLO pose gets `point N` names), clamps coordinates that overshoot the image by rounding, skips and lists invalid annotations, and leaves images with a different size or no annotations alone. Dialogs: `js/labels.js` (gallery toolbar: Export…, Import labels…). Not done: CVAT / Label Studio adapters, RLE masks, dataset versions (Stage 3.2 / 3.3), classification folders.
- **Annotator saving (single path):** all sends go through `saver.js`; leaving the page calls `saver.flushNow({keepalive: true})` (never a separate request: that produced a false 409 and stopped saving). After a conflict, edits still go to the draft. A 4xx other than 409/408/429 is *rejected* (shown with the server's reason, not retried; the next edit tries again).
- **Annotator saving:** every edit writes a synchronous `localStorage` draft (`studio.draft.<imageId>`) and schedules a debounced replace-all `PUT` with the revision; the draft is removed after a successful save and offered back ("Restore") if the tab died first; a `pagehide` `keepalive` request sends anything still pending; a revision conflict (409) shows a banner with "Load the latest" / "Keep my version".

---

## Schema Reference

- DDL: `studio/migrations/001_init.sql` (tables `projects`, `batches`, `images`, `image_tags`) and `002_annotations.sql` (`classes`, `annotations`; `images.marked_empty`, `images.label_class_id`, `images.annotations_rev`). The database is created and owned by this app, so it is writable.
- Inspect: `python -c "import sqlite3; c=sqlite3.connect('data/studio.sqlite'); print(c.execute('select * from projects').fetchall())"` or any SQLite browser. Do not edit rows by hand while the app runs.
- Adding schema: new file `studio/migrations/NNN_name.sql` (next number, no gaps). Never edit an applied migration. Update this section and the tests in the same commit.

---

## Key Conventions

- **`images.width` / `images.height`** are the **EXIF-oriented** dimensions (what a browser shows). The stored original is untouched. Orientations 5–8 swap width and height: `if orientation in {5,6,7,8}: width, height = raw_height, raw_width`. All future annotation coordinates are pixels in this oriented space, origin top-left.
- **`images.split`** — `NULL` means *unassigned* (API/UI name: `unassigned`); otherwise `train` | `val` | `test` (CHECK constraint).
- **`images.sha256`** — hash of the original file bytes; `UNIQUE(project_id, sha256)` is the duplicate rule. Stored file name is `<sha256><lower-case ext>`; thumbnail is `<sha256>.jpg`.
- **Image URLs** carry `?v=<first 12 hex of sha256>` and are served `immutable`; the id alone is not a cache key (ids can be reused after deletes).
- **Tags** are trimmed, lower-case, de-duplicated (`repo.clean_tags`); limits in `config.yaml` → `tags`.
- **Project names** are whitespace-collapsed and unique (case-sensitive in SQL; listing is case-insensitive).
- **Timestamps** are UTC ISO-8601 with `Z`, from `db.utc_now()`.
- **Annotation geometry** (JSON in `annotations.data`, pixels of the oriented image, origin top-left, 2 decimals): box `{x, y, w, h}`; polygon `{points: [[x, y], ...]}`; keypoints `{points: [[x, y, v], ...]}` with `v` 0 not labelled (position stored as 0,0), 1 labelled but hidden, 2 visible. `images.annotations_rev` starts at 0 and +1 on every save; a save with a different `rev` gets 409 `{current_rev}`.
- **Labelled** = has an annotation, or `marked_empty = 1` (explicit "no objects"), or `label_class_id` set (single-label classification). `marked_empty` and annotations are mutually exclusive.
- **Classes**: name unique per project ignoring case; deleting a used class needs `?force=true` (deletes its annotations, clears image labels, bumps their revisions).
- **Config:** all tunables live in `config.yaml`; paths only via `studio/paths.py`.

---

## Data Files

Everything under `data/` is runtime-generated and **gitignored — never commit it** (Development Rule 3).

| Path | Contents |
|------|----------|
| `data/studio.sqlite` (+ `-wal`, `-shm`) | The database |
| `data/projects/<id>/images/` | Copies of imported originals |
| `data/projects/<id>/thumbs/` | JPEG thumbnails |
| `data/tmp/import_*` | Scratch folders for zip extraction; removed after each import |

Deleting a project deletes its rows and its `projects/<id>` folder.

---

## Platform Constraints

- Developed and tested on **Windows 11 / Python 3.13**. Code is OS-neutral (pathlib everywhere); no OS-specific branches yet. Linux/macOS are untested.
- GPU: PyTorch CUDA build from the `cu130` index (see `requirements.txt`). No hardware-dependent code exists in v0.1; hardware samplers (Stage 5) must guard their imports (`try/except ImportError`) and ship fakes.
- Browsers: the UI needs ES modules, `<dialog>`, CSS custom properties and `prefers-color-scheme` (any current Chrome/Edge/Firefox/Safari).

---

## Deployment Notes  [if applicable — TO BE FILLED]

> Dev vs deployment environment table, code transfer command, one-time target setup, pre-deploy checklist, hardware smoke test, config/env differences. Delete if no hardware or remote target.

_Not yet filled — update before the first session._

---

## Known Technical Debt

- **v0.4 (keypoints) independent review: PASS (2026-11-13), its 4 SHOULD and 3 NIT findings fixed the same day; a second review pass was not run.** Edges are only drawn for labelled points; there is no per-point colour; per-point names are not drawn on the canvas (they appear in the inspector and the placement hint; the class label sits above the pose). Changing a class skeleton's length is blocked while keypoint annotations use it, with no migration tool.
- **`tests/test_smoke.py::test_cuda_is_visible_when_present` can fail with a Windows `OSError` loading a torch DLL** when many browser processes are running (seen once after a long browser run; passes when the machine is quiet). `dev_run` start-up also flakes now and then ("Could not connect to the browser's debugging port"); a retry passes.

- **Polygon perf at extremes**: a full inspector render with 50 polygons of 300 points was ~207 ms before the crossing-test cache (`crossingOf`, per points array); now only changed polygons are re-tested. The rubber band redraws only the draft layer. Not re-measured at that extreme.
- **v0.3 review NITs left as debt**: polygon labels can overlap; UI constants (`CLOSE_RADIUS_PX`, `MIN_POINT_GAP_PX`, `DOUBLE_CLICK_GUARD_MS`) live in code.

- **Polygons are hole-free and may cross themselves.** Self-crossing shapes are flagged but accepted (the server only rejects near-zero area). Exporters in Stage 3 must decide how to rasterise or reject them.
- **Midpoint handles are hidden above 150 points** per polygon (too many to be useful); use Simplify or the keyboard (`I`) there. Polygon labels sit at the bounding box's top-left corner and can overlap neighbours.

- **Class-name uniqueness is case-insensitive for ASCII only** (`COLLATE NOCASE`); "Éa" and "éa" can both exist. Fix with a normalised column when classes are exported.
- **Palette contrast**: 9 of the 12 class colours are below 3:1 against the panel background in at least one theme (measured in the v0.2 review). Mitigated, not solved: every swatch/dot has a 1 px ring in `--text-2`, class names always accompany colours, and box labels are white with a black outline (21:1). Revisit with per-theme palette variants.
- **UI constants live in code, not `config.yaml`**: handle size, drag thresholds, nudge steps, retry delays, undo coalescing window (600 ms), zoom limits, `#000` label outline. They are presentation constants, not tunables of the data or hardware; documented here so they are not mistaken for oversights.
- **Narrow screens**: below 900 px the inspector moves under the canvas and the canvas gets small (about 266 px tall at an 800 px high window). Acceptable for a desktop tool; revisit if tablets matter.
- **Process deviation recorded**: in the v0.2 series the backend (8e26bed) and the pure modules (8e10f84) were committed before their docs/index/log entries (ff8ca43). The end state is documented; future steps keep docs in the same commit.

- **Import speed is I/O-bound**: ~36 images/s on 1024×768 JPEGs (2,000 in 55.8 s, measured 2026-11-06, synthetic fresh files). One file at a time. Parallel read/decode (threads) is the next lever if datasets grow beyond a few thousand.
- **Startup migration runs once at `create_app`**, not per process start of workers; fine for one process, revisit with Stage 8 workers.
- **Splits are not stratified** (no labels yet); revisit in Stage 2/3.
- **Test client deprecation warning**: Starlette prefers `httpx2` for `TestClient`; the install was blocked in-session, so tests use `httpx` 0.28.1 and show one warning.
- **Auto-split on a filtered view** always acts on the whole project, not the visible subset.
- **Browser checks are a dev tool, not in `pytest`**: `tools/dev_run.py run smoke` (16 checks with real mouse/keyboard) needs Edge or Chrome and is run by hand before a tag. Extend `tools/scenarios/smoke.py` with every UI bug fixed. It does not run in CI (there is none yet).
- **`dev_run` limits**: it cannot move the operating-system pointer or drive native pop-ups (for example the dropdown list of a `<select>`; the smoke scenario sets those values by script). Window size depends on the screen (1378×791 on this laptop).
- **Zip import extracts everything to disk first** (up to `importing.max_zip_uncompressed_gb`), then imports; large zips need that much temporary space.
- **Orphan files are possible** if the process dies between writing an image's files and committing its row. They are named by hash, so a re-import overwrites them; there is no sweeper yet.
- **A 16384×16384 image** is within `images.max_side_px` but over Pillow's decompression-bomb limit, so it is reported as "oversize" with Pillow's message.
- **Symlink handling is only tested on junctions here**: this account cannot create symlinks (Windows privilege), so that test skips; the code path is shared with junctions.
- **Ids can be reused** after deleting the newest project (`INTEGER PRIMARY KEY` without `AUTOINCREMENT`). Mitigated: creating a project removes any leftover folder for its id. A stale browser tab on a deleted project may show a newer one with the same id.

---

## Development Rules

Referenced by number in TODO items and commit messages.

1. **Local-first privacy.** Dataset images and labels never leave the machine. The only outbound network use is weight downloads and owner-paired workers. No telemetry. *(Owner decision 2026-11-06)*
2. **Neutral storage.** Annotations are stored so they export losslessly to COCO and YOLO; CVAT and Label Studio via adapters. No lock-in.
3. **No dataset in git.** `data/` is gitignored; only small manifests/metrics may be committed.
4. **Licence boundary.** The core never imports Ultralytics YOLO (AGPL). It lives in a separate optional plugin. Record each model-weight licence before adding it.
5. **Clean-room.** Study the reference platform only via public docs, API reference, open-source repos and the owner's own account behaviour. Copy no code or assets. Do not point REA at proprietary hosted clients (`docs/REA.md`).
6. **UX is binding.** No screen ships without passing the checklist in `docs/UX.md`. (UX-1)
7. **Hardware is read at runtime.** Never hard-code GPU, VRAM or core counts; every tunable lives in `config.yaml`.
8. **Every hardware sampler and ML backend has a fake** that runs on any machine, so tests do not need a GPU.
9. **Small tagged versions.** A version is tagged only with passing tests and docs updated in the same commit. Commit at each good step.
10. **Multi-agent process:** follow `docs/AGENTS.md` (builder + independent reviewer by default; crew only where contracts allow; owner approves each stage plan and every tag).

---

## Project TODO List

Legend: 🔴 Bug / rule violation  |  🟡 Incomplete feature  |  🟢 Not started  |  ✅ Done

The live task list is `TODO.md`; the stage plan is `docs/PLAN.md`. Sections above still marked `[TO BE FILLED]` (Running, Architecture, Key Modules, Schema, Conventions, Data Files, Platform, Deployment) are filled as each stage lands code — in the same commit as that code.

---

## User Rules

> Copy **Standard User Rules** from `CLAUDE-COMMON.md` verbatim here, then copy all sections from `PROJ_STARTER.md` below those. Add project-specific overrides at the bottom, clearly labelled.

See `CLAUDE-COMMON.md` → Standard User Rules and `PROJ_STARTER.md` for the full rule set.

### Project-Specific Overrides

- **"Explain before acting" (PROJ_STARTER) is scoped per stage plan** *(owner decision, 2026-11-06)*: for this project, the owner approves each stage plan (files and steps). Inside the approved scope, agents may edit, test and commit without asking again. Anything outside the scope — and always `git push`, version tags, deleting user data, installing system software, or anything outside the repo — still requires explicit approval. Details in `docs/AGENTS.md`.
