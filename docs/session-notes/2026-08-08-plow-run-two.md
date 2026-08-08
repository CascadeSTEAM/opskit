# 2026-08-08 (later) — second /plow run, and the cleanup cycle

Pure public-repo development: issues, PRs, docs, tests. No live infrastructure was
touched, and no node was contacted — every finding below was reached statically.

## What ran

A second `/plow` after the first run's backlog clearance, plus the cleanup cycle the
operator asked to define (#182, #185) and its first real use.

## Merged

| PR | Issue | Summary |
|---|---|---|
| #183 | #182 | The cleanup cycle: skill + `bin/repo-cleanup.py`, wired into `/plow` phase 4 |
| #186 | #185 | Cleanup judges a branch by what it holds, not only by its PR state |
| #188 | #187 | Assert the datacenter firewall before claiming container isolation |
| #190 | #184 | Rescue four items from an abandoned branch |

New issues filed: #184, #185, #189. Cross-linked #168 (unblocked by #188).

## Cleanup, first real use

```bash
bin/repo-cleanup.py            # survey
bin/repo-cleanup.py --apply    # 15 remote branches removed, SHAs printed
git push origin --delete 150-…-proxmox   # provably empty, ancestor of main
```

Undo any of it with `git push origin <sha>:refs/heads/<name>`.

The two branches it withheld turned out to be completely different things — one an
abandoned `gh issue develop` stub with zero unique commits, the other three commits of
real field work. That contrast is what prompted #185.

Incidental finding: those empty stubs are not harmless. `gh issue develop` cannot reuse
a branch name, so an abandoned empty branch silently renames the next attempt at that
issue with a `-1` suffix — which is why #150's real work sat on `…-proxmox-1`, and the
same had happened to #90 and #69.

## Errors and near-misses

**Three defects in a branch-deleting tool, in code I had just shipped.** The cleanup
tool could delete unmerged work three ways: a `CLOSED` (rejected) PR's branch was
treated as merged; a branch force-pushed *after* its PR merged still reported `MERGED`
and was deleted with no ancestry check; and a stacked PR merged into a non-default base
was indistinguishable from one merged into `main`. Fixed by asking `gh` for
`baseRefName` and `headRefOid` and believing `MERGED` only when the tip is still what
was merged *and* it went into the default branch.

Ancestry was also judged against a possibly-stale local ref with no fetch, so a commit
existing only on origin answered "not an ancestor" for want of the object rather than on
the merits.

**A shadowed variable**, caught by my own new tests: the loop's ref-path variable
shadowed the comparison base, so ancestry was checked against the branch itself.

**The same failure mode twice in one fix (#187/#188).** The playbook claimed isolation
while checking two of Proxmox's three conditions. The fix's own opt-out then used
Ansible's `| bool`, which maps any unrecognised string to `false` without complaint — so
`-e require_datacenter_firewall=treu` silently disabled the guard. Also: the detection
matched the *first* `enable: 1` anywhere in the file, so a leftover duplicate
`[OPTIONS]` block could mask an effective `enable: 0`.

**A half-ported fix (#184/#190).** The DNS apex rule went into the *add* step but not
the *verify* step, which would have failed the whole playbook run for exactly the
records the feature exists to support. The guard existed in the source material and was
dropped in transit; no test touched the verify block. A fifth item on that branch
(`caddy_admin_listen`) was missing from the issue's own table and had to be added.

**A lint rule that contradicts a field finding.** `command-instead-of-module` fires on
the `curl` probe and suggests `uri` — the exact module that task exists to avoid,
because `uri` imports python-cryptography on the *target* and fails where
`_cffi_backend` does not match (seen on python3.14). Resolved with a per-line `noqa`
and the reason recorded in the file, never a `skip_list` entry (#83).

## Practice that paid off

Every fix in both runs was **mutation-verified**: revert the fix, confirm the test
fails, restore. That exposed several tests which passed against the very bug they
claimed to guard.

Review agents were pinned to a commit or an isolated worktree, after two of them
produced inconsistent findings when branches moved underneath them mid-review.

## Undo

Each item is a squashed commit on `main`; revert individually with `git revert <sha>`.

`make test` 891 passed / 1 skipped; `make lint` 0 failures.
