# TODO

## In Progress
- [ ] Stage 1 (v0.1): built, reviewed and fixed; waiting for the owner's tag approval (see Not Started → v0.1 items).
- [x] Stage 0 (v0.0) tagged; G3 (worker machines/export priority) still deferred by the owner.

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
- [x] Multi-agent process agreed and written — `docs/AGENTS.md` (2026-11-06).
- [x] Stage 1 (v0.1) plan approved by owner (copy images; folder path import; no datasets table).
- [x] v0.1 built in five commits (aa7024f, b09f5fc, 0c3e2ad, 074deeb, 0add954) — storage, importer, API, UI, speed-up.
- [x] v0.1 independent reviewer pass done (verdict FAIL: 1 blocker + 10 should-fix); findings fixed in c46ca4f (backend) and the following frontend commit; verified by 84 tests + 15 browser checks.
- [x] Tagged `v0.1` on 39f055f (2026-11-07), approved by the owner. No second reviewer pass was run.
- [x] Browser driver `tools/dev_run.py` (option A: own CDP driver, visible by default, real input, on-page cursor) built and verified: smoke 16/16 visible and headless; tour 4/4.
- [x] Stage 2 plan approved by owner 2026-11-07 (single-label, explicit "no objects", key map as proposed); written into `docs/PLAN.md`.
- [ ] Stage 2 v0.2 (boxes + classification): 2.1 backend → 2.2 shell → 2.3 box tool → 2.4 flow; then independent review and owner tag approval.
- [ ] Stage 2 v0.3 (polygons) and v0.4 (keypoints): after v0.2 is tagged.
- [ ] dev_run: pace default for visible runs was chosen by me (1.0, `--pace 0` for instant) because the owner did not answer; confirm or change.
- [ ] v0.1 follow-ups (technical debt in CLAUDE.md): parallel import, move browser checks into a real test runner, `httpx2` for the test client (install was blocked), orphan-file sweeper.
- [x] G1: wrote `docs/FEATURES.md` and `docs/FORMATS.md` (2026-11-06). Cleared for planning.
- [ ] Before Stage 3: verify every `[U]` (unverified) line in `docs/FORMATS.md` (COCO spec, CVAT XML, Label Studio polygon/keypoint, licences) and add golden sample files under `tests/data/formats/`.
- [x] G2: venv, pinned `requirements.txt`, `config.yaml`, `.env.example`, `pyproject.toml`, pytest + ruff, `studio/config.py`; CUDA torch 2.14.1+cu130 verified on Python 3.13.7 (GPU matmul OK). 6 tests pass, lint clean (2026-11-06).
- [ ] G3 (DEFERRED by owner at v0.0): owner to confirm worker machines (OS, GPU, network, offline?) and priority export target. Must be answered before Stage 6 and Stage 8 design.
- [x] Tagged `v0.0` (2026-11-06).
- [ ] Owner to read Roboflow's Terms of Service before further study.
- [ ] Choose project name, accent colour/density, and final licence.
- [x] Node upgraded to 26.13.0, REA 6.8.0 installed and registered with Claude Code only (see `docs/REA.md`). Owner: restart Claude Code to load it.
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
