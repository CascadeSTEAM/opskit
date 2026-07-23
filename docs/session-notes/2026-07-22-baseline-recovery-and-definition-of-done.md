# 2026-07-22 — Recover dropped baseline work + codify a definition of done

Pure public-repo development session (tool + policy). No live infrastructure
was touched.

## Context

A prior OpenCode session died mid-task and left uncommitted work in the tree
with none of the usual housekeeping done: a new `bin/baseline.py` + `baseline`
skill, an idea-ledger row still `new`, no issue/branch, no tests, a stub
`rebuild` subcommand, dead code, and (caught later) a client-token leak. This
session reconstructed the intent from the working tree and finished it "the
right way", then added enforcement so the gap class can't recur.

## What was done

### Baseline feature — PR #38 (Closes #37)
- Triaged idea-ledger row 6 → `accepted` #37 (`bin/idea.py mark`). Scrubbed a
  personal identifier from the row first.
- `bin/baseline.py`: implemented `rebuild` (was `print("... not yet
  implemented")`) — generates a restage script from the saved baseline;
  removed 6 dead `capture_*` helpers superseded by inlined `capture_all`;
  added `OPSKIT_ROOT` override (env-sync.sh / bin/opskit pattern) for testability.
- `tests/test_baseline.py` — 9 tests (save / rebuild / status + parsing helpers).
- Scrubbed real environment names out of the baseline SKILL.md — the
  publication guard caught a client token on commit. Confirms the guard works.

### Definition-of-done enforcement — PR (Closes #39)
- `bin/definition-of-done-guard.py` + `tests/test_definition_of_done_guard.py`.
  Enforces: new `bin/*.py` has a test; new skills registered in AGENTS.md;
  no stub markers in shipped `.py`/`.sh`. Opt-outs: `# dod: no-test`,
  `ALLOW_DOD_SKIP=1`.
- Wired into `.githooks/pre-commit` and a new CI `definition-of-done` job
  (same script both sides — publication-guard pattern).
- `.opencode/rules/definition-of-done.md` (policy) + AGENTS.md Core-Rules
  reference + `endsession` skill gains the agent-verified checklist.

## Commands of note
```
python3 bin/idea.py mark --title "System baseline capture skill" --status accepted --gh 37
gh issue develop 37 --checkout --base main
gh issue develop 39 --checkout --base main
make test            # 90 passed (was 61 pre-session; +17 new + growth)
python3 bin/definition-of-done-guard.py --cached
```

## Errors encountered
- Pre-commit publication guard blocked the first baseline commit on a client
  token in SKILL.md — scrubbed to generic phrasing, re-committed. Working
  as designed.
- Guard `--cached` arg initially collided with an argparse positional; fixed by
  making `--cached` a store_true flag.

## Undo instructions
- Revert PR #38 / the #39 PR via GitHub, or `git revert <merge-sha>`.
- To disable the DoD guard temporarily: `ALLOW_DOD_SKIP=1` on the commit, or
  remove the guard line from `.githooks/pre-commit` and the CI job.

## Open threads
- `ansible.cfg` has an unrelated uncommitted change (deprecated `stdout_callback
  = yaml` → `ansible.builtin.default` + `result_format = yaml`) left over from
  the dropped session. Not part of either PR — needs its own disposition
  (likely a small chore PR or folding into the ERP branch).
- The in-flight ERP feature branch the dropped work was sitting on still has
  its own work, untouched by this session.
