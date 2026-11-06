# AGENTS — how agents build this project

Decided with the owner on 2026-11-06. Binding for every session. Cold-start agents know only the repo and their prompt, so everything they need must be in `CLAUDE.md`, `docs/PLAN.md`, `docs/UX.md` and this file.

## 1. Decisions
| Topic | Decision |
|-------|----------|
| Model | **Builder + independent Reviewer (A)** by default. A stage moves to a **parallel crew (B)** only when its seams are clean *and* its contracts are written first. Full six-role team (C) is not used. |
| Merging | Auto-merge to `main` after QA passes. **The owner approves every version tag.** |
| QA gate | Tests + lint · Development Rules + licence review · UX checklist (screens) · docs updated in the same commit |
| Handoff | Role cards here; per-stage contracts in `docs/CONTRACTS.md` (create when the first crew stage needs it) or the stage's section in `docs/PLAN.md` |
| Autonomy | The owner approves each **stage plan** (files and steps). Inside that scope agents build, test and commit freely. Anything outside the scope stops and asks. |

**Always needs the owner's approval, regardless of scope:** `git push`, deleting user data or files outside the approved scope, installing system software or changing system settings, anything outside the repo, version tags, and changing a Development Rule.

## 2. Workflow per version
1. **Plan** — Builder drafts the stage plan: goal, files to create/change, steps, tests, UX criteria, which model (A or B). Posts it to the owner.
2. **Approval** — Owner says go (or edits). Nothing is built before this.
3. **Build** — Builder works on a short-lived branch `v0.X/<topic>` (or in the main checkout for model A when the owner prefers), committing at each good step (owner request: never lose progress). Docs, TODO and log are updated in the same commits.
4. **QA** — a fresh-context Reviewer agent runs the checklist in §4 against the diff. It may not edit code; it reports findings. Builder fixes; Reviewer re-checks.
5. **Merge** — fast-forward or merge commit to `main` once QA passes. Delete the branch.
6. **Tag request** — Builder reports results (tests, UX checklist, known gaps) and asks the owner to approve the tag. Tag only after approval.

## 3. Role cards
### Builder (model A: the main session)
- **Job:** implement the approved plan; keep changes inside its scope.
- **Inputs:** approved stage plan, `CLAUDE.md`, `docs/PLAN.md`, `docs/UX.md`.
- **Outputs:** code + tests + docs + commits; a hand-off note for the Reviewer (what changed, how to run, known gaps).
- **Must:** write tests for happy path and key failures; read tunables from `config.yaml`; follow `PROJ_STARTER.md` (explicit code, DRY, no deprecated APIs).
- **Must not:** push, tag, widen scope, import Ultralytics in core, commit data.

### Reviewer / QA (fresh context, read-only)
- **Job:** judge the diff against written rules, not against the Builder's intent.
- **Inputs:** the diff, `CLAUDE.md`, `docs/PLAN.md`, `docs/UX.md`, this file's checklist.
- **Tools:** read, run tests/lint/the app; **no code edits**.
- **Output:** a findings list — each with file:line, rule number, severity (blocker/should/nit) and a reproduction. Ends with PASS or FAIL. A blocker means FAIL.
- **Must:** actually run `pytest` and `ruff`, not trust the Builder's report; open every changed screen against the UX checklist; check licences of any new dependency or weight.

### Backend / Frontend / Docs (crew stages only, model B)
- **Backend:** `studio/` Python package, API, DB, workers. Owns the API contract server side.
- **Frontend:** `studio/web/` only. Codes against the contract; uses design tokens; never calls undocumented endpoints.
- **Docs:** `docs/`, `TODO.md`, log, index; only if the Builder delegates. Otherwise the Builder keeps docs in the same commit.
- **Rule:** each crew agent edits only its own paths. Contract changes go through the Builder, never unilaterally. Each works in its own git worktree on its own branch.

## 4. QA checklist (Reviewer)
- [ ] `python -m pytest -q` passes; new behaviour has tests (happy path + failure modes + edge cases).
- [ ] `python -m ruff check .` clean; `python -m py_compile` clean.
- [ ] **Development Rules 1–9** (see `CLAUDE.md`): no data leaves the machine; neutral storage; no dataset in git; no YOLO import in core; clean-room respected; UX checklist; no hard-coded hardware/tunables; fakes for samplers/backends; docs and tests in the same commit.
- [ ] New dependency or weight: licence recorded, compatible with the permissive core; pinned in `requirements.txt` with a reason.
- [ ] UX checklist in `docs/UX.md` §9 for every new or changed screen (keyboard-only, contrast, states, undo, progress).
- [ ] Docs: `TODO.md`, `.CLAUDE/CLAUDE-LOG.md`, `docs/PLAN.md` status, `.CLAUDE/CLAUDE_INDEX.md` (if a file was added) updated in the same commit.
- [ ] Secrets: none in code, config or commits; `.env.example` lists any new variable.
- [ ] Scope: every changed file is inside the approved plan.

## 5. Branches and worktrees
- Model A: work on `main` directly for small steps, or on `v0.X/<topic>` for anything risky. Reviewer runs against the branch.
- Model B: one worktree per crew agent, e.g. `../studio-wt/v0.3-backend` on branch `v0.3/backend`, `…/v0.3-frontend` on `v0.3/frontend`. The Builder merges them after QA. Worktree folders live **outside** the repo directory and are deleted after merge.
- Never rebase or merge `main` with `machine-vision` (Branch Policy).

## 6. Contract template (for crew stages)
```
Contract: <name>   Stage: <n>   Status: draft | agreed
Owner: Backend | Frontend
Endpoints / schema: <method path -> request -> response -> errors>
Events (WebSocket): <name -> payload>
Invariants: <what must always hold>
Test fixtures: <where sample data lives>
Changes require: Builder approval; bump the version here.
```

## 7. When to choose a crew (model B)
Use B only if **all** hold: the work splits into disjoint paths; the contract can be written in under a page; each side can be tested alone with a fake of the other; the expected saving outweighs the extra briefing and merge cost. Likely candidates: Stage 5 monitor (sampler backend vs dashboard UI), Stage 6 training UI vs trainer. Stage 1–2 stay model A.

## 8. Failure handling
- Reviewer FAIL → Builder fixes and requests re-review; do not merge on a blocker.
- A scope question mid-build → stop, ask the owner, record the answer in the log.
- Disagreement between Reviewer and Builder → owner decides; record the decision in `docs/PLAN.md`.
- Never claim a check passed without running it.
