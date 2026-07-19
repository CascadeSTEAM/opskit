# Rule: Commit Message Format

All commit messages MUST follow this format:
```
<type>: <ticket-prefix>-XXXX — <description>
```

Valid types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

The ticket prefix is read from `environments/$ACTIVE_ENV/env.yml` → `ticket.prefix`.
Include it whenever a ticket is open — the pre-commit hook validates it for any
staged files under `ansible/`, `inventory/`, or `environments/<env>/` (excluding example/).

The description is a brief summary in lowercase (no trailing period).

Examples:
- `feat: TKT-0085 — add Proxmox live source to inventory sync`
- `fix: CS-0026 — correct Caddy routing for helpdesk`
- `docs: update node documentation` *(no ticket required for docs-only)*
