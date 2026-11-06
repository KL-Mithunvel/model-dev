# Claude Log

## 2026-11-06 — Scoping a local Roboflow-style app; no code written
- Owner first asked to clone `github.com/morluto/rea` (MIT, TypeScript MCP server for AI-driven reverse engineering; needs Node 22+/24+/26+ and an installed Ghidra/IDA/Hopper/Kuna for native targets). Inspected it read-only via its GitHub page; nothing was cloned.
- Owner then redirected: build a local, offline, privacy-first alternative to Roboflow (projects, dataset import, annotation, AI-assisted labeling, model training, live CPU/GPU/hardware monitoring, workload sharing). Planned as a multi-stage, multi-agent, small-versions effort.
- Decisions so far:
  - App form: local web app (FastAPI backend, thin vanilla-JS frontend), per `PROJ_STARTER.md`.
  - rea's role: learn Roboflow's feature set and document how to implement similar functionality. Clean-room only — no copying Roboflow code or assets. Assistant advised staying on observable behaviour and public docs, and checking Roboflow's terms of service.
  - rea is to be integrated only where relevant (a tool, not merged into app code) — exact placement still open.
- Open questions sent to owner (answers pending): where the project lives (this repo is the template library, and its Branch Policy keeps `main` generic — a separate repo is recommended), annotation approach (build vs CVAT vs Label Studio; comparison given), training stack and licensing (Ultralytics is AGPL), AI-assist method, hardware sensors, workload-sharing model, multi-agent roles, release cadence.
- Environment note from the earlier survey: RTX 1000 Ada, 6 GB VRAM — the design must assume a small GPU.
- Noted: `machine-vision` is not listed by `git branch -a` although the log says it was pushed; probably needs `git fetch`. Not investigated.
- Files changed: this log, `TODO.md`, `README.md` (was empty).

## 2026-11-06 (2) — REA set up as a gitignored tool; plan work begins
- Owner answered all 13 scoping questions (see `docs/PLAN.md` once written): app lives on `main`; just the owner; detection + classification + segmentation + keypoints, images only; build our own annotator with COCO/YOLO neutral formats and CVAT/Label Studio adapters; ML-backend protocol with SAM, zero-shot and active-learning backends; permissive models plus optional Ultralytics YOLO plugin; ONNX/TFLite/TensorRT/PyTorch export; hardware monitor incl. Intel Arc/NPU; remote training workers; Apple HIG principles for UX; multi-agent process deferred to the start of coding.
- Cloned `morluto/rea` (shallow, `ad518cf`, v6.8.0) into `tools/rea/`, added it to `.gitignore`, reviewed DISCLAIMER, SECURITY and `install.sh`. Did not run `npm install` or `rea setup`: Node here is v24.16.0 and REA needs ≥ 24.22.1.
- REA's DISCLAIMER excludes tampering with online services and copying proprietary code/assets, so it will not be pointed at Roboflow's hosted client; the clean-room scope stays public docs, open-source repos and own-account behaviour. Recorded in the new `docs/REA.md`.
- Wrote `docs/UX.md` (1f23679) and `docs/PLAN.md` (3c1a6a3); updated `.CLAUDE/CLAUDE.md` (Branch Policy now allows the app on `main`; Project Overview, Preflight Gates and Development Rules filled). Remaining template sections stay `[TO BE FILLED]` until code lands.
- REA set up with owner approval: `winget upgrade OpenJS.NodeJS.LTS` → Node 26.13.0; `npm install --global rea-agents@6.8.0`; dry-run of `rea setup` shown, then `rea setup --client claude_code --yes` applied (edited `~/.claude.json` with backup, installed skill). Doctor healthy; no analysis engine installed; `frida` install script left blocked. Setup command exited 255 only because the environment check found no engine.
- Stage 0.2 / Gate G1: read public Roboflow docs (home, adding data, dataset versions, models), Ultralytics YOLO label docs (detect, segment, pose), CVAT formats list and Label Studio export docs; wrote `docs/FEATURES.md` and `docs/FORMATS.md`. Several pages did not render (COCO spec, CVAT XML structure, Label Studio polygon value), so those lines are tagged `[U]` unverified rather than guessed; they must be checked before Stage 3. No Roboflow code or assets used; REA not used on Roboflow.
- Stage 0.3 / Gate G2 cleared: created `venv/`; installed `torch==2.14.1+cu130` and `torchvision==0.29.1+cu130` from the PyTorch cu130 index (cu128 tops out at 2.11, cu130 has the newest builds for Python 3.13). `torch.cuda.is_available()` is True on the RTX 1000 Ada (6140 MB); a 1024×1024 CUDA matmul ran. No fallback to Python 3.12 was needed. Survey re-run inside the venv shows CUDA available.
- Added `requirements.txt` (pinned), `config.yaml`, `.env.example`, `pyproject.toml` (pytest, ruff), `studio/__init__.py`, `studio/config.py`, `tests/test_smoke.py`. `ruff` flagged E501 in the template's `tools/compute_survey.py`; exempted that one file instead of reformatting it. `python -m pytest`: 6 passed.
- G3 (worker machines and export targets) is still open; it does not block this skeleton but blocks Stage 6–8 design.
- Owner asked to tag `v0.0` while G3 was unanswered: tagged anyway, with G3 recorded as deferred by the owner (PLAN.md Stage 0.4, TODO). Then opened the multi-agent process discussion.
- Owner message ".+3" arrived mid-session and was unintelligible; asked for a resend. Not acted on.
- Compute survey, full laptop: Dell Precision 3591, Core Ultra 7 155H (16C/22T), 31.5 GB RAM, RTX 1000 Ada 6 GB, Intel Arc iGPU, 410 GB free disk, Python 3.13.7, torch not installed.

## 2026-09-28 — Record the never-merge branch policy
- Owner clarified that `main` and `machine-vision` are separate personal copies and are never to be merged. Added a "Branch Policy" section (marked repo-specific, not to be copied into new projects) at the top of `.CLAUDE/CLAUDE.md` on `main`, and matching notices on `machine-vision`.
- Cancelled the TODO item to merge `main` into `machine-vision`; recorded the reason there. The earlier merge of `origin/main` into `main` is unaffected — that was the same branch on the remote.
- Improvements are shared between the branches by copying text by hand as a separate commit on the target branch, after asking the owner.

## 2026-09-28 — Move claude_MV to a branch; bring generic rules back to main
- Created and pushed branch `machine-vision` (924a9c1) with the full contents of KL-Mithunvel/claude_MV. `main` stays the generic template.
- Reviewed the vision material for generic value and applied the selected items to `main`:
  - `.CLAUDE/CLAUDE-COMMON.md`: added Documentation Discipline (non-code docs go in `docs/`, not `project/` — decided to match the new Standard Project Layout), Secrets & Credentials, and Preflight Gates with three generic example gates (understand the existing state, survey the environment, confirm where it will run). Added a "no hardcoded parameters" rule for all projects, a Preflight Gates slot in the template skeleton, and a Standard Project Layout section.
  - `.CLAUDE/CLAUDE.md`: added a `## Preflight Gates` placeholder section.
  - New `.gitignore` (generic subset — vision image/weights blocks left on the branch) and `tools/compute_survey.py` (docstring generalised; ran it on this machine, works on Windows: RTX 1000 Ada, 6 GB VRAM, torch not installed).
  - `.CLAUDE/CLAUDE_INDEX.md` now committed on `main` with a Tooling and Defaults section.
- Edited `CLAUDE-COMMON.md` at the owner's request, despite the `update-docs` skill's note that it is normally not edited.
- Not applied (recorded in `TODO.md`): dependency-pin rule, failed-experiments rule, provisional-values rule, honest-reporting rule, rule → evidence style, log-file naming housekeeping, and the personal-preference items.
- Left for later: merging `main` into `machine-vision` will conflict in `CLAUDE-COMMON.md` and `CLAUDE_INDEX.md`.
- Decision: `compute_survey.py` was run with system Python because this repo has no venv; it is standard library only and read-only.
- Push of `main` was rejected: `origin/main` already had PR #3 (Documentation Discipline + "ok KLM" opener in `PROJ_STARTER.md`, merged 2026-06-18). Merged it into local `main` (no force-push). Git merged cleanly but left two Documentation Discipline sections in `CLAUDE-COMMON.md`; removed the remote's copy and kept the `docs/` version (owner's decision). The "ok KLM" opener is now active on `main`.
