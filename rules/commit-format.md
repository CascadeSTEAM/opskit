# Rule: Commit Message Format

All commit messages MUST follow this format:
```
<type>: <ticket-id> — <description>
```

Valid types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

The ticket ID comes from `.current-ticket` (e.g. `TKT-0085`, `CS-0022`).
Include it whenever a ticket is open — the pre-commit hook validates it for any
staged files under `ansible/` or `inventory/`.

The description is a brief summary in lowercase (no trailing period).

Examples:
- `feat: TKT-0085 — add Proxmox live source to inventory sync`
- `fix: CS-0026 — correct Caddy routing for CLIENT1 helpdesk`
- `docs: update Proxmox node documentation` *(no ticket required for docs-only)*
