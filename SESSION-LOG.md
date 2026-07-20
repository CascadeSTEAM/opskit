# SESSION-LOG

Strategic index of work sessions on the opskit tool itself: key decisions,
architectural choices, open threads. Detailed operational notes live in
`docs/session-notes/`.

**Client-data policy:** sessions operating a *client environment* are logged in
that environment's gitignored layer — `environments/<env>/session-notes/` —
never here. This file and `docs/session-notes/` are published; they may only
describe tool development, phrased client-agnostically. See
`docs/client-data-policy.md`.

---

## 2026-07-20 — Client-data isolation policy

**Key decisions:**
- The public repo, its issues, PRs, and commit messages must contain zero
  client-identifying information; client work is tracked in the client's
  helpdesk and the gitignored environment layer
- Commit messages reference tickets as `TKT-<num>`; the client-identifying
  helpdesk prefix stays local (`.current-ticket`) and in the helpdesk
- Pre-commit/commit-msg hooks actively block client tokens and RFC1918
  addresses in anything staged for publication
