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
