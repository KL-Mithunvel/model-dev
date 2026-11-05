# TODO

## In Progress
- [ ] Scope the local Roboflow-style app: collect owner's answers to the open questions (location, annotation approach, training stack, AI-assist, hardware monitor, workload sharing, agent roles, release cadence), then write the multi-stage plan.

## Done
- [x] Create the `machine-vision` branch holding the claude_MV baseline (four gates, docs, tools, Roboflow skills) — pushed to origin (924a9c1 on `machine-vision`).
- [x] Add generic rules from the machine-vision work to `CLAUDE-COMMON.md` — Documentation Discipline, Secrets & Credentials, Preflight Gates (with three example gates), "no hardcoded parameters" for all projects, Standard Project Layout, and a Preflight Gates slot in the skeleton and in `CLAUDE.md`.
- [x] Add baseline `.gitignore` and `tools/compute_survey.py` (generalised docstring; verified on Windows 11).

- [x] Integrate `origin/main` PR #3 (Documentation Discipline + "ok KLM" opener) — merged; removed the duplicate Documentation Discipline section, keeping the `docs/` version. The "ok KLM" opener is now on `main`.
- [x] ~~Merge `main` into `machine-vision`~~ — CANCELLED. The owner keeps the two branches as separate personal copies and never merges them. Added a "Branch Policy" section to `.CLAUDE/CLAUDE.md` so future AI sessions know.

## Not Started
- [ ] Write the multi-stage / multi-phase / multi-agent plan for the local Roboflow-style app in full (goal, steps, files, success criteria per phase) before any code, with small tagged versions.
- [ ] Decide where the app lives (recommended: new sibling repo, since `main` here must stay a generic template) and create it from this template.
- [ ] Decide how `morluto/rea` is brought in (installed tool, vendored under `tools/rea/`, or separate clone); not yet cloned.
- [ ] Clean-room study of Roboflow's feature set (public docs, API reference, observable behaviour) documented under `docs/`; owner to confirm Roboflow's terms allow the planned use.
- [ ] Run `tools/compute_survey.py` for the new project and record the result (preflight gate); last known: RTX 1000 Ada, 6 GB VRAM.
- [ ] Investigate why `machine-vision` is not listed by `git branch -a` (likely needs `git fetch`).
- [ ] Pin dependencies that silently break: record the pin, the reason, and a verification command (machine-vision Development Rule 7).
- [ ] Record failed experiments and attempts with their numbers (machine-vision Development Rule 8).
- [ ] Label provisional values as provisional in code and docs until confirmed (machine-vision Development Rule 6, needs rewording beyond hardware thresholds).
- [ ] Honest-reporting rule: state what each number was measured on, compare like with like, treat tiny deltas as noise (needs rewording without model/val-set language).
- [ ] "Rule → evidence" style: every template rule carries a one-line "why this exists".
- [ ] Housekeeping: pick one log file location and name. `CLAUDE-COMMON.md` says root `Claude_log.md`; this repo keeps `.CLAUDE/CLAUDE-LOG.md` and the index points there.
- [ ] Personal preference to decide: whether "explain before acting" gets an "unless autonomous completion was asked for" clause. (The "ok KLM" opener is done — see Done.)
