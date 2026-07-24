# 2026-07-23 — /gh workflow skill, tool fixes, trusted-tester bring-up

Pure public-repo development plus one live env operation (logged privately).
Public tooling work is recorded here; the trusted-tester bring-up touched live
infrastructure and is logged only in the relevant environment's private
`session-notes/` (publication policy — no infrastructure state here).

## Shipped (all via the definition-of-done flow: issue → linked branch → make test → PR)
- **`/gh` workflow skill + `bin/fix-issue.sh`** — codifies the 8-step issue-fix
  protocol (assign → worktree → linked branch → plan-to-issue → implement →
  test → PR-that-closes → review → cleanup). Subcommands: `setup`, `pr`,
  `cleanup`, `list mine|unassigned`, `search`, `new` (guided issue creation with
  native GitHub issue **Types** + `priority:*` labels + dedup), `bump`. Issues
  #50/#52/#54 → PRs #51/#53/#55. Dogfooded (the skill's own follow-ups were run
  through it; PRs opened by `fix-issue.sh pr`).
- **Review step uses built-ins** — `/gh` step 6 now calls Claude Code's
  `/code-review` + `/security-review` instead of hand-written prose (#57 → #58).
- **`bin/ap.sh` fix** — exports `ANSIBLE_CONFIG` so role-based playbooks resolve
  `roles_path` after the `cd` into `ansible/` (ansible discovers `ansible.cfg`
  only in cwd, not up-tree). +`OPSKIT_ROOT` test override, tests (#46 → #49).
- **`bin/open-ticket.sh` fail-loud** — a configured helpdesk that fails to create
  a ticket no longer silently writes a local placeholder + exits 0 (which the
  commit-msg guard would accept as a real ticket). Now: exit 1 with an actionable
  message; explicit `--local` opt-in; fixed a double-prefix bug in local ids;
  `OPSKIT_ROOT` override + tests (#47 → #56).
- **ansible collections** — `requirements.yml` + gitignore the installed
  `ansible_collections/` (#45 → #48). **ansible.cfg** — modernized the deprecated
  yaml stdout callback (#41 → #42). **gitleaks** — wired into pre-commit + CI with
  a tuned `.gitleaks.toml` (#43 → #44).
- Created `priority:high|medium|low` labels; adopted the org's native issue
  **Types** (Task/Bug/Feature) for classification.

## Live env op (private)
A trusted-tester workstation for a hardware-firmware project was brought up
remotely (repos cloned, flash toolchain installed, device detected) and a Fabric
driver + plan were captured in that environment's private layer. Details,
credentials handling, and the reusable-installer requirements note live there /
in the firmware project — deliberately not here.

## Errors / notes
- The publication guard correctly blocked two client-token leaks mid-session (a
  skill doc's example env names, and a commit message) — scrubbed before publish.
- A local vs CI divergence surfaced: the local publication guard (case-sensitive,
  local `.client-tokens`) passed a token that CI's `CLIENT_TOKENS` secret caught.
  Follow-up: make the guard case-insensitive / align the local token list.

## Undo
- Revert any PR via GitHub or `git revert <merge-sha>`; each shipped item is a
  separate squash-merge (#42/#44/#48/#49/#51/#53/#55/#56/#58).

## Open threads
- **Tooling-consolidation proposal** (drafted, not filed): one GitHub
  issue/PR methodology across projects — a self-hosted GitHub MCP (primitives) +
  a distributable orchestration skill (merging `/gh` and the ported
  `docwright-issue-workflow`) + thin per-project config. Recommend filing it.
- **DoD guard weakness** — its skill-registration check uses substring matching
  (a 2-char skill name like `gh` matches incidentally); make it match the
  skills-list line specifically. (Ledger-worthy.)
- **Branch-name guard gap** — `publication-guard.sh` doesn't check branch names,
  though the client-data rule forbids client-identifying ones (ledger row 7).
- Add the new `definition-of-done` + `gitleaks` CI jobs to main's *required*
  branch-protection checks so they gate merges.
- Rotate/scope the broad PAT placed on the tester box (tracked privately).
