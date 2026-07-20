# Rule: Commit Message Format

All commit messages MUST follow this format:
```
<type>: TKT-<number> — <description>
```

Valid types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Commit messages reference tickets in the neutral form `TKT-<number>` (e.g. `TKT-0085`).
The environment's real ticket prefix (`environments/$ACTIVE_ENV/env.yml` → `ticket.prefix`)
and the full prefixed ID live only in `.current-ticket` and the helpdesk — they must
never appear in commit messages.
Include the ticket whenever one is open — the pre-commit hook validates it for any
staged files under `ansible/`, `inventory/`, or `environments/<env>/` (excluding example/).

The description is a brief summary in lowercase (no trailing period).

Examples:
- `feat: TKT-0085 — add Proxmox live source to inventory sync`
- `fix: TKT-0026 — correct Caddy routing for helpdesk`
- `docs: update node documentation` *(no ticket required for docs-only)*
