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

The app server (`python -m studio`) does not exist yet — it arrives in Stage 1.

---

## Architecture  [TO BE FILLED]

> Module responsibilities table (file → role). Data flow diagram (ASCII). Threading or async model. Simulation vs real mode and how to switch.

_Not yet filled — update before the first session._

---

## Key Modules  [TO BE FILLED]

> One subsection per file or logical group. Public interface: function names, parameters, return types, exceptions raised. Side effects and I/O.

_Not yet filled — update before the first session._

---

## Schema Reference  [if applicable — TO BE FILLED]

> Path to DDL/schema file, read-only vs writable, tooling for inspection, annotated schema doc. Delete this section if the project has no data layer.

_Not yet filled — update before the first session._

---

## Key Conventions  [if applicable — TO BE FILLED]

> Universal row keys, encoded fields with full encode AND decode formulas, sentinel values, current-record pattern, per-tenant partitioning, env vars. Delete if no non-obvious encoding exists.

_Not yet filled — update before the first session._

---

## Data Files  [TO BE FILLED]

> What is stored, where, and whether it is git-tracked. Runtime-generated vs committed files. Files that must never be committed.

_Not yet filled — update before the first session._

---

## Platform Constraints  [TO BE FILLED]

> Target OS(es), platform-specific libraries and their guards, hardware dependencies and dev-mode equivalents.

_Not yet filled — update before the first session._

---

## Deployment Notes  [if applicable — TO BE FILLED]

> Dev vs deployment environment table, code transfer command, one-time target setup, pre-deploy checklist, hardware smoke test, config/env differences. Delete if no hardware or remote target.

_Not yet filled — update before the first session._

---

## Known Technical Debt  [TO BE FILLED]

> Existing rule violations (file + line), temporary workarounds. Do not omit — document so debt is not accidentally perpetuated.

_None recorded yet._

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
