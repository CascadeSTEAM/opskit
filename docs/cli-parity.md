# CLI parity — the `opskit` command surface (#104)

Every capability reachable through a conversational agent should also be
runnable directly from `opskit` — no agent runtime, no MCP server, no shell
wrapping a prompt. This file is the architectural decision those ports all
follow, settled once so individual capabilities stay consistent.

## Decision: the CLI is a vencer over the MCP tool modules

Chosen option from #104: **CLI drives the MCP tools.** An `opskit`
subcommand imports the capability's `mcp/*-mcp-server.py` module (e.g.
`technitium-mcp-server.py`), dispatches to its `@mcp.tool` function, and does
all output shaping itself.

Why not the shared-core extraction? Cost. The tool functions are already
tested; a veneer reuses that coverage with zero drift risk, and the MCP shape
(tool functions returning JSON strings) is exactly what a thin CLI adapter
can absorb in one function. The shared-core option is reserved for a
capability that grows a second non-CLI, non-MCP consumer, or whose core needs
tests that cannot go through the MCP function signature.

## The vencer pattern (the pattern later ports copy)

1. **Resolve the module** from the script location (`SCRIPT_DIR.parent /
   "mcp" / ...`), never from the data root — `OPSKIT_ROOT` in tests points at
   a temp root with no `mcp/`, and the capability code lives with the CLI,
   not the data.
2. **Dispatch** to the tool function inside a try/except. `KeyboardInterrupt`
   → 130; any other exception → `ERROR: <msg>` on stderr, exit 1.
3. **Shape the output** in the adapter only:
   - human-pretty by default (`json.dumps(..., indent=2)`)
   - `--json` → compact single-line JSON
   - a result carrying an `"error"` key → printed, exit 1
   - non-JSON pass-through (e.g. cache-flush text) → printed as-is, exit 0
4. **Exit codes:** 0 success, 1 operational error, 2 usage error (argparse),
   130 interrupted.

## Conventions

- The subcommand appears in `opskit --help` (argparse subparsers), in the
  bash and zsh completion scripts, and in the help epilog examples.
- Credentials resolve exactly as they do for the MCP server (env / `.env` via
  the server's own `load_env()`); the CLI adds no credential surface.

## Reference implementation

`opskit dns` (servers / zones / records / compare / flush) is the first port
and the pattern to copy. Later ports on the same model: helpdesk tickets,
Proxmox inspection, WireGuard peers, device inventory.