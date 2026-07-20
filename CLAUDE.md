# CLAUDE.md

See **`AGENTS.md`** — that is the actual project-orientation doc, kept
vendor-neutral on purpose so OpenCode, Claude Code, other agents, and humans
all share one source of truth (`opencode.json` points there too).

This file exists only because Claude Code looks for `CLAUDE.md` specifically;
its content is intentionally not duplicated here so the two files cannot
drift apart.

Quick start:
- Read `AGENTS.md` in full before acting — the Behavioral Hard Rules and the
  Git & GitHub Workflow (Hard Rules) sections are mandatory.
- Session start: `git fetch --all --prune && git pull`, verify
  `core.hooksPath` is `.githooks`, then `bin/switch-env.sh <env>` +
  `bin/open-ticket.sh` before any infra change.
- Issue work: `gh issue develop <n> --checkout` — never commit issue work on `main`.
