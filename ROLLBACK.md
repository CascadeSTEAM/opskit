# Rollback & Emergency Procedures

If a PR merges and later breaks the test suite or project stability, use this
procedure to recover quickly. (Adapted from the lilyetibot project's
ROLLBACK.md.)

Full test gate referenced below:

```bash
.venv/bin/python -m pytest tests/
```

## Quick diagnosis: Is this a real blocker?

1. **Reproduce locally:**
   ```bash
   git fetch --all --prune && git pull
   .venv/bin/python -m pytest tests/
   ```
   If tests pass, the issue might be environment-specific (missing dependency,
   flaky test). Move to Procedure 2.
2. **Check what merged recently:** `git log --oneline -5 main`
3. **Assess impact:**
   - Suite fails completely / tooling broken → rollback immediately (Procedure 1).
   - Some tests fail → investigate first (Procedure 2).
   - Slow/flaky test → investigate, don't roll back.

## Procedure 1: Rollback (fast recovery)

```bash
git log --oneline main | head -10        # find the merge commit of the broken PR
git revert -m 1 <merge-commit>           # -m 1 keeps main, discards the PR branch
git push origin main
.venv/bin/python -m pytest tests/        # verify recovery
```

Then comment on the reverted PR: what failed, with the test output, and ask the
author to investigate and reopen. **Time: ~5 min.**

## Procedure 2: Investigate (thoughtful recovery)

```bash
.venv/bin/python -m pytest tests/ 2>&1 | tee test-output.log
git log --oneline -S "<failing symbol>" main | head -5   # did the PR change the code or the test?
```

Decide:
- Test too strict (behavior changed correctly) → update the test in a fix PR.
- Code wrong → roll back (Procedure 1) and have the author re-investigate.
- Flaky/environmental → file an issue for the flake; don't roll back.

**Time: 15–30 min.**

## Procedure 3: Hotfix (if rollback broke something else)

```bash
git revert <revert-commit>               # if the revert itself was wrong, revert it
# otherwise:
git checkout -b hotfix/emergency-fix-main
# minimal change to get the suite green
.venv/bin/python -m pytest tests/
git push -u origin hotfix/emergency-fix-main
```

Open a PR titled `[HOTFIX] …`, explain the issue, land it fast — minimal
review, but tests always run first. **Time: 30–60 min.**

## Post-incident: Document & prevent recurrence (mandatory)

Rules evolve from mistakes — every incident must leave the repo harder to break:

1. **Add a regression test** that would have caught it (or, if the failure was
   process-shaped, a pre-commit/CI guard — see the private-IP guard in
   `.githooks/pre-commit` for a worked example).
2. **Comment on the merged PR** with the specific failure and prevention steps.
3. **Update docs/rules** if the failure revealed a spec or documentation gap.
4. **Capture any follow-up ideas** in the ledger: `bin/idea.py add …`
5. Close the incident issue once the fix is merged.

## Prevention: Before merging

1. Merge only green PRs — the full suite, not a subset.
2. Author syncs main into the branch and re-runs tests before the final merge.
3. Review for edge cases: unhandled exceptions, incomplete refactors,
   hardcoded environment data (public repo!).

## TL;DR

| Scenario | Action | Time |
|----------|--------|------|
| Suite completely broken | Rollback (Procedure 1) | 5 min |
| Some tests fail, unclear why | Investigate (Procedure 2) | 15–30 min |
| Rollback caused new failures | Hotfix (Procedure 3) | 30–60 min |
| Not sure which | Rollback first, then investigate | 5 + 15–30 min |
