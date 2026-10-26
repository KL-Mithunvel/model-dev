# Claude Log

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
