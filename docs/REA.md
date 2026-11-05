# REA (morluto/rea) — how we use it

## What it is
REA ("Reverse Engineer Anything") is an MIT-licensed MCP server (npm package `rea-agents`, TypeScript) that lets an AI agent inspect binaries, JavaScript/Electron apps, .NET assemblies, APKs, websites, firmware and packet captures locally, and report evidence. Official sources only: <https://github.com/morluto/rea>, <https://rea.tools/>, the `rea-agents` npm package.

## Status in this repo
| Item | State |
|------|-------|
| Local clone | `tools/rea/` — shallow clone, **gitignored, not committed** |
| Pinned commit | `ad518cff65cc71564f678b26bcae4a3862689ad4` (package `rea-agents` 6.8.0, 2026-11-06) |
| Installed / registered with Claude Code | **No.** `npx rea-agents setup` has not been run |
| Blocker | Node.js on this machine is v24.16.0; REA needs `^22.23.4 \|\| ^24.22.1 \|\| >=26.12.1`. Upgrade Node first (owner's decision). |

Why a gitignored clone and not vendored source: REA is a tool our agents call, not a library our app imports. Committing 7,000+ third-party files would bloat history and blur licences. Re-create the clone with:

```bash
git clone --depth 1 https://github.com/morluto/rea tools/rea
git -C tools/rea checkout ad518cff65cc71564f678b26bcae4a3862689ad4   # needs a full fetch if the pin moves
```

## Review findings (read before first use)
- `install.sh` only runs `npm install --global rea-agents@<version>` and then optionally `rea setup`. It supports macOS and Linux only, not native Windows; on Windows use `npm install --global rea-agents` directly.
- `rea setup` edits agent configuration (MCP registration, workflow instructions, backups). It shows a plan and needs approval. Review the plan before approving.
- SECURITY.md: REA is **not a sandbox**. Opening an untrusted binary delegates parsing to the local analysis provider with the user's permissions. Use a throwaway environment for untrusted targets.
- Native analysis needs an installed provider (Ghidra + JDK, Hopper, IDA or Kuna). Static JavaScript analysis needs none.

## Allowed use in this project (clean-room rule)
Decision (owner, 2026-11-06): we study Roboflow only through public documentation, its API reference, its open-source repositories (`supervision`, `inference`, `rf-detr`), and behaviour visible in the owner's own account. We write our own specification and build from it. No Roboflow code or assets are copied.

REA's own DISCLAIMER.md excludes "tampering with online services", accessing systems you are not authorised to test, and "copying proprietary software or reproducing its protected code and assets". Therefore:
- **Do not point REA at Roboflow's hosted web client or any proprietary component.**
- REA remains useful for software we are entitled to examine: open-source tools we adopt ideas from (for example an annotation UI's published source), our own builds, and third-party formats we must interoperate with.
- Roboflow's Terms of Service should still be read by the owner before any further study; this file does not give legal advice.

## Next steps (owner decisions)
1. Upgrade Node to ≥ 24.22.1 (or 22.23.4+/26.12.1+) if REA is wanted.
2. Run `npm install --global rea-agents`, then `rea setup` and review its plan.
3. Pick a first allowed target (see TODO.md).
