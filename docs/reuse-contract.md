# The reuse contract — consuming OpsKit's tooling from another repo

Sibling projects reinvent the same scaffolding: `AGENTS.md` in ~18 of them,
paired `.claude/`+`.opencode/` in 10+, `.githooks/` reimplemented in 5. The
*concept* is duplicated everywhere; the *content* legitimately differs, so "one
shared skills directory" is the wrong answer.

But one class is already **not** independently reimplemented: the guards and
launchers. `buildsmith/tools/guard.py` calls this repo's
`bin/publication-guard.sh` rather than reimplementing the token and RFC1918
checks. That prototype is the design — this document makes it a supported
contract instead of an accidental one.

**Owner decision (2026-08-05): env-var delegation is the standard reuse
mechanism. No submodules, no packaging.**

## What may be consumed

Only the **executable tooling** tier: guards, launchers, `automation-ladder.py`,
MCP servers. Consume it *by reference* — invoke it where it lives.

Two tiers are explicitly **not** consumed this way:

- **Conventions** (`AGENTS.md` shape, session-log lifecycle, hooks) — same
  shape, different content. Scaffold from a template plus a drift check.
- **Skills** — content is legitimately per-project. Share the *scaffolding*
  (frontmatter validation, the skill-builder, the divergence guard), never the
  skills themselves. Copying skills is what produced #131: two trees, nine
  divergent pairs. It also produced the DocWright imports deleted there — a
  second maintained copy is the disease, not the cure.

## The contract

### Locating OpsKit

`OPSKIT_ROOT` names where OpsKit lives. Default it to `~/Projects/opskit`, but
always allow the environment to override it.

**Fail closed if it is missing.** A consumer that silently skips the guard when
OpsKit is absent is strictly worse than one with no guard, because it reports
success. Say so loudly and refuse.

### Naming the tree under test

```bash
"$OPSKIT_ROOT/bin/publication-guard.sh" --repo /path/to/your/repo --cached
```

`--repo` sets the tree being checked while token sources still come from
`OPSKIT_ROOT`. It is accepted in **any** argument position — a trailing
`--repo` used to be silently ignored, which made the guard report clean about
a repo it never looked at. Without it, both default to `OPSKIT_ROOT` — which
is why this repo's own hooks pass no arguments.

Before `--repo` existed, a consumer had to point `OPSKIT_ROOT` at *itself* and
feed tokens in through `CLIENT_TOKENS`, overloading one variable with two
meanings. That workaround still functions, but new consumers should use
`--repo`.

### Checking the version

```bash
"$OPSKIT_ROOT/bin/publication-guard.sh" --contract-version   # -> integer
```

Assert a minimum and **fail closed below it**. This is the "staleness must be
loud" requirement: a consumer pinned to behavior that has since changed must
say so rather than silently run a check that no longer means what it did.

`CONTRACT_VERSION` is bumped whenever something observable to a consumer
changes — a new mode, a changed exit code, a changed output shape. Adding a
pattern to an existing check is not a contract change.

### Confirming the token list is not empty

```bash
"$OPSKIT_ROOT/bin/publication-guard.sh" --token-count   # -> integer
```

An empty token list makes the token check a no-op that is indistinguishable
from passing — the dangerous failure this whole design exists to prevent. A
consumer that wants to fail closed on it needs the count, and **only** the
count: the tokens themselves are the secret being protected, so the guard never
prints them and neither should you.

Before this existed, `buildsmith` reimplemented `collect_tokens()` in Python
purely to test emptiness — forking the token logic, the one thing the
delegation was meant to avoid.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | checks passed |
| 1 | a check failed — something must not be published |
| 2 | the guard could not run (bad `--repo` path) — treat as failure |

Never treat a non-zero exit as "skip and continue".

## Worked example

```bash
OPSKIT_ROOT="${OPSKIT_ROOT:-$HOME/Projects/opskit}"
GUARD="$OPSKIT_ROOT/bin/publication-guard.sh"

[ -x "$GUARD" ] || { echo "ERROR: OpsKit guard missing at $GUARD"; exit 1; }

want=1
have="$("$GUARD" --contract-version)" || exit 1
[ "$have" -ge "$want" ] || {
    echo "ERROR: OpsKit guard contract v$have, need >= v$want. Update OpsKit."
    exit 1
}

[ "$("$GUARD" --token-count)" -gt 0 ] || {
    echo "ERROR: OpsKit's client-token list is empty — the token check would be"
    echo "       a silent no-op. Refusing (fail closed)."
    exit 1
}

exec "$GUARD" --repo "$(pwd)" "$@"
```

## What a consumer still owns

Delegation covers what is *shared*. Anything about your own layout stays yours,
because only you can see it: a neutrally-named private directory trips no token,
so only your repo can catch a file escaping from it. `buildsmith` keeps its
site-isolation check locally for exactly this reason, and that is correct.

## Adding to the contract

New modes are additive: add the mode, bump `CONTRACT_VERSION`, document it here,
and cover it in `tests/test_publication_guard.py` — **both** directions, the
denied case and the allowed case. A guard is only as good as its list, and the
allowed cases are what stop the list growing until people disable it.
