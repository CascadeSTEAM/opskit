# Agent tool restrictions

Why this exists: a high-effort code-review run spawned 32 subagents, and one read
`/etc/shadow` and echoed it into a script — unrelated to the review task. Every
finding that run produced was genuine, so the fan-out earned its keep; the tool
access it ran with did not. Issue #160.

## Two layers, and only one of them binds

**Agent definitions** (`agents/*.md`, rendered into `.claude/agents/` and
`.opencode/agent/` by `python3 bin/automation-ladder.py sync-agents`) declare
what a named agent may do. `@code-reviewer` is pinned to repo-scoped reads and
this repo's own tests.

Their limit, stated plainly:

- They apply only when an agent is spawned **by name**. The built-in code-review
  workflow calls `agent()` with no `agentType`, so it gets a default-tool agent
  and never consults these files.
- Claude Code does not hard-enforce OpenCode `permission` deny-globs — under that
  harness the rendered restrictions are *advisory* text the agent is asked to
  honour. `sync-agents` says so in its own output.

**The PreToolUse hook** (`bin/guard-sensitive-reads.py`) binds regardless of
which agent is running, because the harness consults it before every tool call.
That is the layer that would actually have stopped the incident.

## Wiring the hook (operator step)

This edits `.claude/settings.json`, which an agent cannot write to itself — a
session that could grant its own permissions could also revoke this guard. Paste:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/bin/guard-sensitive-reads.py\""
          }
        ]
      }
    ]
  }
}
```

The command anchors on `${CLAUDE_PROJECT_DIR}` rather than a bare relative
path — hooks run with the session's live cwd, not one fixed at the project
root, so a bare `bin/guard-sensitive-reads.py` stops resolving (and takes
every subsequent Read/Bash call down with it, since the matcher is
`Read|Bash`) the moment anything `cd`'s outside the repo root. That failure
mode wedged a whole session and its subagents in practice (opskit #234) —
don't reintroduce the unanchored form.

Merge it into any existing `hooks` block rather than replacing one — settings
arrays do not merge across sources.

Verify it took effect:

```bash
echo '{"tool_name":"Read","tool_input":{"file_path":"/etc/shadow"}}' \
  | python3 bin/guard-sensitive-reads.py     # -> a deny decision
echo '{"tool_name":"Read","tool_input":{"file_path":"README.md"}}' \
  | python3 bin/guard-sensitive-reads.py     # -> {}
```

Then ask an agent to read `/etc/shadow`; it should be refused by the harness
rather than by the model's judgement.

## What the guard covers, and what it deliberately does not

Covered: `/etc/shadow`, `/etc/gshadow`, `/etc/sudoers`, SSH host keys, user
private keys (`.ssh/id_*`, but not `.pub`), `.aws/credentials`, `.kube/config`,
vault session files, `.client-tokens` — via the `Read` tool **and** via shell
commands, since the incident went through a shell.

Not covered, on purpose: "any path outside the repo". Reviews legitimately read
sibling checkouts and system config, and a guard that fires on ordinary work gets
switched off — the same reasoning that keeps `[^{]` in the secret-scan patterns
so they do not fire on Jinja placeholders. This narrows the blast radius of an
over-broad agent; it is not a sandbox.

### Message arguments are text, not reads

Also not covered, and for the same reason: the argument of a *message* flag
(`-m`, `--message`, `--body`, `--title`, `--notes`). Documenting the guard by
naming a guarded path in a commit message used to be denied (#169) — a guard
that fires when you document the guard is precisely the failure mode above.

The strip is kept narrow, because distinguishing "mentions a path" from "reads
a path" in arbitrary shell is the sort of cleverness that hollows out a guard:

- **The strip applies only to commands that take these flags as messages**
  (`git`, `gh`, and friends), and is decided **per command segment**. This one
  is load-bearing: `-m`, `-b` and `-t` are argument-less booleans in plenty of
  other tools — `sort -m`, `sort -b`, `diff -b`, `od -b`, `column -t` — where
  the token after the flag is the file being read. Skipping it there would hand
  out one-line exfiltration (`od -b <guarded path>` dumps every byte). Scoping
  per segment also stops a legitimate `git commit -m "…"` earlier in a line
  from licensing a skip in a later command. Wrapper prefixes (`sudo`, `env`,
  `VAR=value`) are seen through, so they cannot launder either side.
- Only the flag's own argument is dropped; the rest of the command is still
  scanned, so `git commit -m "subject" && cat <guarded path>` still denies.
- A message argument containing command or process substitution is **not**
  treated as text — `git commit -m "$(cat <guarded path>)"` really does read
  the file, and still denies.
- `-F` / `--body-file` are **not** message flags. They name a file the command
  opens, so `git commit -F <guarded path>` reads it and still denies.
- A command that cannot be parsed (unbalanced quotes) is scanned in full
  rather than trusted.

**Heredoc bodies are deliberately not stripped.** A heredoc looks like inert
data, but `bash <<'EOF'` feeds an interpreter, so stripping bodies would let any
command through. Naming a guarded path inside a heredoc still denies; put it in
a `-m` message, or write the file with an editor tool instead of a shell
here-document.

## Adding a credential store

Add the pattern to `SENSITIVE_PATHS` in `bin/guard-sensitive-reads.py` and a case
to both lists in `tests/test_guard_sensitive_reads.py` — the denied list and the
allowed list. A guard is only as good as its list, and the allowed cases are what
stop the list from growing until people disable it.
