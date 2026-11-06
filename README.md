# model-dev

A personal library of `CLAUDE.md` project briefs and workflow rules for AI-assisted development with Claude Code. Files here are templates and reference material for new projects.

## Layout

| Path | Purpose |
|------|---------|
| `.CLAUDE/CLAUDE.md` | Project template — copy into new projects |
| `.CLAUDE/CLAUDE-COMMON.md` | Universal workflow rules |
| `.CLAUDE/PROJ_STARTER.md` | Personal preferences and tech stack defaults |
| `.CLAUDE/CLAUDE_INDEX.md` | Master index of the documents above |
| `.CLAUDE/CLAUDE-LOG.md` | Session log |
| `.CLAUDE/skill/` | Custom Claude Code skills |
| `TODO.md` | Task tracker |
| `tools/compute_survey.py` | CPU/RAM/disk/GPU survey (preflight gate) |

## Branches

`main` is the generic template. `machine-vision` is an independent personal copy with a machine-vision baseline. They are never merged — see the Branch Policy in `.CLAUDE/CLAUDE.md`.

## Running the app

```powershell
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu130
venv\Scripts\activate
python -m studio          # then open http://127.0.0.1:8000
python -m pytest -q
python tools\dev_run.py open     # app + demo data in a browser window; Ctrl+C to stop
python tools\dev_run.py run tour # watch a narrated, scripted walk through the app
```

Details, architecture and conventions: `.CLAUDE/CLAUDE.md`. Plan: `docs/PLAN.md`.

## Current direction

Planning a local, offline, privacy-first alternative to Roboflow (dataset import, annotation with AI assistance, model training, live hardware monitoring) as a separate project. See `TODO.md` and `.CLAUDE/CLAUDE-LOG.md` for status.
