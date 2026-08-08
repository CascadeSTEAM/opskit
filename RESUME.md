# RESUME — picking the work back up

Written at the end of the 2026-08-08 sessions. Read this, then `AGENTS.md`.

## Open risk worth carrying forward

**The datacenter firewall state is unverified in every environment.** #188 stops the
provisioning playbook from *claiming* isolation it cannot deliver, but containers
provisioned before that fix may be reachable while their config says otherwise. Nobody
has touched a node. First step of #189, and it is a live-session task.

## State right now

- `main` is clean, synced, and green: `make test` 891 passed / 1 skipped, `make lint` 0 failures.
- **No open PRs.** No work in flight, nothing uncommitted, all four environment layers pushed.
- 19 issues closed across the two `/plow` runs; the backlog below is what remains.

## Start here

```bash
git fetch --all --prune && git pull
bash bin/setup-hooks.sh --check          # core.hooksPath must be .githooks
bin/repo-cleanup.py                      # what the last run left behind
```

Then pick an issue and use the normal workflow: `gh issue develop <n> --checkout`,
**verify the branch actually switched** (see Gotchas), work it, full `make test`,
PR with an external reviewer requested.

## The backlog, ordered

**Ready to work — repo-only, no live access needed**

| Issue | What | Note |
|---|---|---|
| #177 | Scripted session shutdown | `endsession` is still a manual checklist; that is what caused ledger row 10. Two sibling projects have one to adopt from — adopt and own, never copy. |
| #176 | Conventions-tier scaffold + drift check | The larger half of #138. Executable tooling is already handled by the reuse contract; this is the `AGENTS.md`-shape tier. |
| #181 | Validator vs scanner record shape | `validate-datasets.py` uses a flat schema; the scanner reads/writes nested. Needs a ruling on which is canonical, then the other side fixed. |
| #168 | Tinker interop | Repo-side parts (playbooks, guard inheritance, AGENTS.md pointer) are ready. **The vault collection is live work** — needs its own session. Unblocked by #188. |

**Needs an operator decision before code**

| Issue | Decision |
|---|---|
| #189 | Whether to enable the datacenter firewall. **Check its live state first** — see Open Risk. |
| #170 | ~20 tracked files carry client-token hits. Per-hit calls: scrub, or refine the token list. Run `bin/publication-guard.sh --tree` locally; **its output is client-identifying, keep it local**. |
| #159 | Step 1 answered (nothing to cut over — our file wraps the same package). Step 2 is yours. |
| #104 | Umbrella; needs the architectural choice recorded before capabilities are ported one at a time. |

**Blocked on hardware**

- #94, #106 — both need a live RouterOS device.

## Gotchas that cost time this session

1. **`gh issue develop <n> --checkout` sometimes does not switch the working tree** in
   this clone — it prints the remote's new-branch line either way. A commit went to
   `main` because of this. Always run `git branch --show-current` before the first
   `git add`. If it happens: cherry-pick to the issue branch, `git revert` on `main`,
   never force-push. Note `git rebase` will then *skip* the commit as patch-equivalent
   to the revert — reset the branch to `main` and cherry-pick again.
2. **Review agents must pin a commit or worktree** (`git worktree add /tmp/x <sha>`).
   Several sessions share this clone and branches move underneath a reviewer, which
   produced inconsistent findings twice before they re-pinned.
3. **Mutation-verify every fix**: revert it, confirm the test fails, restore. This
   caught three tests that passed against the bug they claimed to guard.
4. **A skipped test is worse than the bug it hides.** `pytest.importorskip` at module
   level silently dropped 13 tests; declare the dependency instead.

## Decisions made this session that later work should not re-litigate

- **Credentials** (`docs/credential-lifecycle.md`): the vault owns the value, the
  inventory owns the metadata, Ansible reads from the vault at run time. Syncing into
  `ansible-vault` was rejected.
- **Cross-repo reuse** (`docs/reuse-contract.md`): executable tooling by reference with
  a version; conventions by scaffold-plus-drift-check; **skills never shared as content**.
- **One skill tree**: `.opencode/skills/` is canonical; `AGENTS.md`'s list is the
  arbiter of what is ours.
- **Cleanup** runs at the end of every `/plow`, reports first, and is *not*
  pre-authorized.

## One loose end

`origin/erp-stack-single-site-multihost-and-dns` still exists. Its content is now on
`main` (#190), so it is safe to delete — but deletion is the operator's call:

```bash
git push origin --delete erp-stack-single-site-multihost-and-dns
# recover: git push origin fc9c40c:refs/heads/<name>
```
