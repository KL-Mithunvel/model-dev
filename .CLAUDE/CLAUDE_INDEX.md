# CLAUDE_INDEX.md

Master index of all documents in this `.CLAUDE/` library. Every new project-based document added to this directory must get an entry here.

---

## Core Documents

| File | Role | Read when |
|------|------|-----------|
| [CLAUDE.md](CLAUDE.md) | Project template — all `[TO BE FILLED]` sections, plus the IMPORTANT notices at the top | Starting any new project or session |
| [CLAUDE-COMMON.md](CLAUDE-COMMON.md) | Universal workflow rules — companion files, deployment model, commands & workflow, template skeleton, examples | Always — read this first |
| [PROJ_STARTER.md](PROJ_STARTER.md) | Personal preferences — interaction rules, coding standards, tech stack choices, commit style | Always — copy into every new project's User Rules |
| [CLAUDE_INDEX.md](CLAUDE_INDEX.md) | This file — master document index | Whenever adding a new document to `.CLAUDE/` |

## Session Files

| File | Role | Read when |
|------|------|-----------|
| [TODO.md](../TODO.md) | Task tracker — in progress, done, not started | Every session to pick up where things left off |
| [CLAUDE-LOG.md](CLAUDE-LOG.md) | Session log — dated entries of what was done and why | Every session start; append before closing |

## Tooling and Defaults

| Path | Role | Read when |
|------|------|-----------|
| [../tools/compute_survey.py](../tools/compute_survey.py) | Compute survey (CPU, RAM, disk, GPU) — used by the "Survey the environment" preflight gate | Before compute-heavy development in any project |
| [../tools/ui_smoke.py](../tools/ui_smoke.py) | Browser smoke test: starts its own server, drives headless Edge/Chrome, 15 UI checks | Before tagging any version that changes the UI; add a check per UI bug fixed |
| [../.gitignore](../.gitignore) | Baseline ignore list — venvs, `.env`, `data/`, IDE and OS files | Copying into a new project |

## Project Docs

| Path | Role | Read when |
|------|------|-----------|
| [../docs/PLAN.md](../docs/PLAN.md) | Local Vision Studio plan: decisions, architecture, gates, stages and versions, risks | Start of every session on the app |
| [../docs/AGENTS.md](../docs/AGENTS.md) | How agents build here: models, role cards, per-version workflow, QA checklist, approval limits | Before planning or starting any stage |
| [../docs/UX.md](../docs/UX.md) | UX rules from Apple HIG principles: tokens, accessibility, shortcuts, per-screen checklist | Before building or reviewing any screen |
| [../docs/FEATURES.md](../docs/FEATURES.md) | Clean-room notes on the reference platform's features and our approach per feature (Gate G1) | Before designing any feature |
| [../docs/FORMATS.md](../docs/FORMATS.md) | COCO / YOLO / CVAT / Label Studio format summaries, verified vs unverified marked | Before Stage 3 and any import/export code |
| [../docs/REA.md](../docs/REA.md) | How the third-party REA tool is cloned, pinned, reviewed and allowed to be used (clean-room rule) | Before using or installing REA |

## Skills

| Path | Role |
|------|------|
| [skill/](skill/) | Custom Claude Code slash commands for this repo — see subdirectory for individual skill files |

---

## How to Add a New Document

1. Create the file in `.CLAUDE/`.
2. Add a row to the relevant section above (or create a new section if it doesn't fit).
3. Include: filename as a relative markdown link, one-line role description, and when to read it.
4. Commit the new file and this index together in the same commit.
