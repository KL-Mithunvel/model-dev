# REA (morluto/rea) — how we use it

## What it is
REA ("Reverse Engineer Anything") is an MIT-licensed MCP server (npm package `rea-agents`, TypeScript) that lets an AI agent inspect binaries, JavaScript/Electron apps, .NET assemblies, APKs, websites, firmware and packet captures locally, and report evidence. Official sources only: <https://github.com/morluto/rea>, <https://rea.tools/>, the `rea-agents` npm package.

## Status in this repo
| Item | State |
|------|-------|
| Local clone | `tools/rea/` — shallow clone, **gitignored, not committed** |
| Pinned commit | `ad518cff65cc71564f678b26bcae4a3862689ad4` (package `rea-agents` 6.8.0, 2026-11-06) |
| Node.js | Upgraded 2026-11-06 from 24.16.0 to **26.13.0** via `winget upgrade OpenJS.NodeJS.LTS` (npm 11.20.0). REA needs `^22.23.4 \|\| ^24.22.1 \|\| >=26.12.1`. |
| Installed | `npm install --global rea-agents@6.8.0` (user prefix `%APPDATA%\npm`); `rea --version` → 6.8.0 |
| Registered with Claude Code | **Yes** (2026-11-06): `rea setup --client claude_code --yes` edited `%USERPROFILE%\.claude.json` (backup `.claude.json.rea.backup`) and installed the skill at `%USERPROFILE%\.claude\skills\reverse-engineer-anything`. Restart Claude Code to load it. Other clients were not configured. |
| Doctor | `healthy: true`; `environment_healthy: false` because no analysis engine is configured (command exits 255 for that reason) |
| Skipped | `frida` install script blocked by npm (only needed for runtime instrumentation); Ghidra, IDA, JADX, Kuna not installed |

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
1. Restart Claude Code so the REA MCP server and skill load; run `rea doctor` to re-check.
2. Pick a first allowed target (see TODO.md). Static JavaScript/Electron analysis works without an engine, e.g. `rea analyze-javascript-application <path> --json`.
3. Native binaries need an engine: Ghidra 12.1.x + JDK (set `GHIDRA_INSTALL_DIR`), or Hopper/IDA/Kuna. Not installed; ask before adding.
4. To undo: restore `%USERPROFILE%\.claude.json.rea.backup`, delete the skill folder above, `npm uninstall --global rea-agents`.
