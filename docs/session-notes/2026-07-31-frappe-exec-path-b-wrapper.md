# Session Note — 2026-07-31

## Work Done
- Resolved issue #71 (Frappe/ERPNext access: one sanctioned execution path).
- Added `bin/frappe-exec.py`, the single sanctioned Path B (SSH + `docker
  exec` + bench) wrapper, engineering out the three recurring defects
  structurally rather than documenting them again:
  - never `bench console` — always the bench venv python (`python -`)
  - never `docker cp` — the caller's script is base64-embedded into a small
    harness and streamed over stdin, so no file is ever written in the
    container
  - never a bare `bench execute` call — the harness always prints exactly
    one JSON envelope `{"ok", "result", "error"}` on stdout, so `0`/`[]`/
    `""`/`None` round-trip unambiguously instead of printing nothing
  - centralizes `frappe.init(site=...)`/`connect()`/`set_user(...)`/
    `db.commit()`/`rollback()` so callers supply only their logic
  - data-driven: reads `frappe.site`/`container`/`ssh_alias`/`venv_python`/
    `user` from `environments/$ACTIVE_ENV/env.yml`, overridable with CLI
    flags; added the optional `frappe:` block to `schemas/env.schema.json`
    and to `environments/example/env.yml`
  - `--print` dry-run mode shows the exact command + harness size without
    touching a live container — this is what makes the tool unit-testable
    without live infrastructure
- Fixed the auth defect in `mcp/erpnext-mcp-server.py` (Path A): replaced
  hardcoded `Administrator` + plaintext-`.env` password with configurable
  per-tenant API key/secret token auth (`Authorization: token <key>:<secret>`,
  resolved from `ERPNEXT_API_KEY[_TENANT]`/`ERPNEXT_API_SECRET[_TENANT]`).
  No new users created — this only makes the existing low-privilege service
  account's credentials configurable. Preserved the existing tool behavior
  and the clear, actionable missing-credential error.
- Added the `frappe-access` skill (`.opencode/skills/frappe-access/SKILL.md`,
  56 lines) documenting the routing rule: Path A (HTTP/API) by default, Path
  B (`bin/frappe-exec.py`) only when the API is unavailable (TLS failure,
  host down) or the operation genuinely needs admin. Registered in
  `AGENTS.md`'s skills list and Tool Scripts table.
- Added `tests/test_frappe_exec.py` (mocked `subprocess.run`, zero live
  calls): falsy-value round-tripping (`0`/`[]`/`""`/`None`/`False`/`{}`),
  no `docker cp` in any generated command, venv python used instead of
  `bench console`, `--print` dry-run never invokes a subprocess,
  `env.yml`-vs-CLI-flag precedence, and remote failure modes (nonzero exit,
  non-JSON output, a remote-reported error).

## Key Decisions
- Envelope shape settled as `{"ok": bool, "result": <any>, "error": str|null}`
  on both the local wrapper's stdout and the harness's stdout inside the
  container — the local wrapper mostly just forwards the remote envelope
  unchanged, and reuses the exact same shape for its own pre-flight/transport
  failures (missing site/container, ssh/docker launch failure, timeout,
  non-JSON remote output) so a caller only ever needs to parse stdout as
  JSON, never branch on exit code semantics first.
- User script is embedded via base64 rather than string-interpolated, so
  arbitrary quotes/newlines/backslashes in the caller's script can never
  corrupt the generated harness — sidesteps injection/quoting bugs entirely
  rather than trying to escape correctly.
- Did not extend Path A's record surface (party records / relationships)
  the issue's "proposed approach" step 2 describes, or address the
  ansible-vault vs. script/MCP tool-placement ambiguity noted as a
  dependency — both are explicitly out of scope for this issue's
  deliverables and are called out as follow-up below.

## Errors Encountered
- None — `make test` (140 passed), `make lint` (informational pre-existing
  shellcheck note in `bin/switch-env.sh`, unrelated), and `make guard` all
  passed on the first attempt after the initial draft.

## Undo Instructions
- Revert the PR / delete the branch after closing:
  `git push origin --delete 71-frappeerpnext-access-one-sanctioned-execution-path-engineer-out-three-recurring-defects`,
  then `git branch -D <branch>` locally.
- On a checked-out branch: `git checkout main -- bin/ mcp/erpnext-mcp-server.py
  schemas/env.schema.json environments/example/env.yml AGENTS.md`, then
  `rm -rf .opencode/skills/frappe-access tests/test_frappe_exec.py`.

## Verification
- `make test`: 140 passed (115 pre-existing + 25 new in
  `tests/test_frappe_exec.py`).
- `make guard` (publication guard) and `python3 bin/definition-of-done-guard.py
  --cached` both passed before commit.
- `python3 -m py_compile` on both new/changed Python files.
- Manually exercised `bin/frappe-exec.py --print` with and without
  `--ssh-alias`, with missing `--site`/`--container`, and with an
  `environments/<env>/env.yml` `frappe:` block to confirm CLI-flag-overrides-
  env.yml precedence, before writing the equivalent automated tests.

## Next Steps
- PR open, `Closes #71`, reviewer `CascadeSTEAM/technology-support`,
  assignee self.
- Follow-up (not done here, per issue's own sequencing notes): extending
  Path A's API coverage to the full record surface (parties/relationships),
  and the separate tool-placement-rule issue the original issue calls out
  as a dependency for whether Path B belongs in `bin/` vs. an Ansible role.
- The issue also notes real use is blocked on a development instance
  existing (this tooling mutates records and must not be developed against
  production) — this session's tests mock every subprocess/HTTP call so
  nothing here required or touched live infrastructure, but first live use
  of `bin/frappe-exec.py` still needs that dev instance.
