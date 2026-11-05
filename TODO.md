# TODO

## In Progress
- [ ] Stage 0 (v0.0) of `docs/PLAN.md`: reference notes (G1), environment + CUDA torch (G2), worker/export confirmation (G3).

## Done (this project)
- [x] Scoping questions answered by owner (2026-11-06) — decisions recorded in `docs/PLAN.md` §1.
- [x] Multi-stage plan written — `docs/PLAN.md` (3c1a6a3).
- [x] UX guide based on Apple HIG principles — `docs/UX.md` (1f23679).
- [x] REA cloned (gitignored), reviewed, documented — `docs/REA.md` (ad6dc12).
- [x] `.CLAUDE/CLAUDE.md` updated: app lives on `main`, project overview, gates, development rules.

## Done
- [x] Create the `machine-vision` branch holding the claude_MV baseline (four gates, docs, tools, Roboflow skills) — pushed to origin (924a9c1 on `machine-vision`).
- [x] Add generic rules from the machine-vision work to `CLAUDE-COMMON.md` — Documentation Discipline, Secrets & Credentials, Preflight Gates (with three example gates), "no hardcoded parameters" for all projects, Standard Project Layout, and a Preflight Gates slot in the skeleton and in `CLAUDE.md`.
- [x] Add baseline `.gitignore` and `tools/compute_survey.py` (generalised docstring; verified on Windows 11).

- [x] Integrate `origin/main` PR #3 (Documentation Discipline + "ok KLM" opener) — merged; removed the duplicate Documentation Discipline section, keeping the `docs/` version. The "ok KLM" opener is now on `main`.
- [x] ~~Merge `main` into `machine-vision`~~ — CANCELLED. The owner keeps the two branches as separate personal copies and never merges them. Added a "Branch Policy" section to `.CLAUDE/CLAUDE.md` so future AI sessions know.

## Not Started
- [x] ~~Write the multi-stage plan~~ — DONE: `docs/PLAN.md` (3c1a6a3). Multi-agent part deferred (see below).
- [x] ~~Decide where the app lives~~ — DECIDED: on `main`, no new repo; Branch Policy updated.
- [ ] Discuss and agree the multi-agent process (roles, worktrees, merge rules) in detail before Stage 1 code.
- [ ] G1: write `docs/FEATURES.md` (clean-room notes on the reference platform) and `docs/FORMATS.md` (COCO/YOLO/CVAT/Label Studio).
- [ ] G2: create venv, `requirements.txt`, `config.yaml`, `.env.example`, pytest skeleton; install CUDA torch and verify the GPU on Python 3.13 (else 3.12).
- [ ] G3: owner to confirm worker machines (OS, GPU, network) and needed export targets.
- [ ] Owner to read Roboflow's Terms of Service before further study.
- [ ] Choose project name, accent colour/density, and final licence.
- [ ] Owner: upgrade Node to ≥ 24.22.1, then install REA and run `rea setup` (see `docs/REA.md`); currently blocked on Node v24.16.0.
- [ ] Choose a first allowed REA target (open-source or owned software; not Roboflow's hosted client).
- [x] ~~Clean-room study ... documented under `docs/`~~ — superseded by the G1 item above (`docs/FEATURES.md`).
- [x] ~~Run `tools/compute_survey.py`~~ — DONE 2026-11-06 (RTX 1000 Ada 6 GB, 31.5 GB RAM, 22 threads); recorded in the log.
- [ ] Investigate why `machine-vision` is not listed by `git branch -a` (likely needs `git fetch`).
- [ ] Pin dependencies that silently break: record the pin, the reason, and a verification command (machine-vision Development Rule 7).
- [ ] Record failed experiments and attempts with their numbers (machine-vision Development Rule 8).
- [ ] Label provisional values as provisional in code and docs until confirmed (machine-vision Development Rule 6, needs rewording beyond hardware thresholds).
- [ ] Honest-reporting rule: state what each number was measured on, compare like with like, treat tiny deltas as noise (needs rewording without model/val-set language).
- [ ] "Rule → evidence" style: every template rule carries a one-line "why this exists".
- [ ] Housekeeping: pick one log file location and name. `CLAUDE-COMMON.md` says root `Claude_log.md`; this repo keeps `.CLAUDE/CLAUDE-LOG.md` and the index points there.
- [ ] Personal preference to decide: whether "explain before acting" gets an "unless autonomous completion was asked for" clause. (The "ok KLM" opener is done — see Done.)
