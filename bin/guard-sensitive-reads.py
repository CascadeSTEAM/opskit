#!/usr/bin/env python3
"""guard-sensitive-reads.py — PreToolUse hook denying credential-store reads.

opskit #160. A high-effort review workflow spawned 32 subagents and one read
`/etc/shadow` and echoed it into a test script — unrelated to the review, and
possible only because nothing constrained it. Agent *definitions* cannot stop
that: the built-in review workflow spawns default-tool agents and never consults
`agents/*.md`, and Claude Code does not hard-enforce OpenCode `permission` deny
globs (see `bin/automation-ladder.py sync-agents`). A PreToolUse hook does bind,
because the harness consults it before every tool call regardless of which agent
is running.

Deliberately narrow: it denies reads of *credential stores*, not "files outside
the repo". A review legitimately reads a sibling checkout or a system config, and
a guard that fires on ordinary work gets disabled — the same reasoning that keeps
`[^{]` in the secret-scan patterns.

Wire it up (see docs/agent-tool-restrictions.md):

    "hooks": {"PreToolUse": [{"matcher": "Read|Bash",
      "hooks": [{"type": "command",
                 "command": "python3 bin/guard-sensitive-reads.py"}]}]}

Reads the hook payload on stdin, prints a permission decision as JSON, exit 0.
"""

from __future__ import annotations

import json
import re
import shlex
import sys

# Credential stores and private keys. Patterns, not exact paths: /etc/shadow-
# and /etc/shadow.bak hold the same hashes.
SENSITIVE_PATHS = [
    re.compile(r"/etc/(shadow|gshadow|sudoers)\b"),
    re.compile(r"/etc/ssh/ssh_host_\w+_key\b"),          # host private keys
    re.compile(r"(^|/)\.ssh/id_\w+(?!\.pub)\b"),         # user private keys
    re.compile(r"(^|/)\.aws/credentials\b"),
    re.compile(r"(^|/)\.kube/config\b"),
    re.compile(r"(^|/)bw-session\b"),                    # vault session token
    re.compile(r"(^|/)\.client-tokens\b"),
]

REASON = (
    "Denied: {target} is a credential store. Reviewing or operating this repo "
    "never requires reading one, so this is either a mistake or out of scope "
    "(opskit #160). If a task genuinely needs a secret, resolve it through the "
    "vault: bin/bw_session.py + bin/mcp-run.sh."
)


# Flags whose argument is a *message* — text that is written, never opened
# (opskit #169). Documenting the guard by naming a guarded path in a commit
# message was denied, which is the "fires on ordinary work" failure mode the
# design doc warns gets guards switched off.
#
# Scoped to the commands that actually take these flags as messages. `-m`, `-b`
# and `-t` are argument-less booleans in plenty of other tools — `sort -m`,
# `od -b`, `diff -b`, `column -t` — where the following token is the file being
# read, not a message. Skipping it there would hand out a one-line exfiltration
# path (`od -b <credential store>`), so the command name gates the whole rule.
#
# `-F`/`--body-file` are excluded on purpose even here: they name a file the
# command opens, so `git commit -F /etc/shadow` really does read it.
MESSAGE_COMMANDS = {"git", "gh", "glab", "hub", "jj"}
MESSAGE_FLAGS = {"-m", "--message", "-b", "--body", "-t", "--title", "--notes"}

# Short flags whose value may be attached (`-mfix typo`). Long flags use `=`.
_ATTACHABLE_SHORT = {"-m", "-b", "-t"}

# Wrappers that prefix a real command without changing what it is.
_COMMAND_PREFIXES = {"sudo", "env", "command", "nice", "nohup", "time", "doas"}

# Operators that end one command and begin another.
_SEGMENT_SEPARATORS = {"&&", "||", "|", ";", "&", "|&", "\n"}

# A message argument is only inert if the shell will not run anything to build
# it. `git commit -m "$(cat /etc/shadow)"` reads the file, so a token carrying
# command or process substitution is never treated as a message.
_SUBSTITUTION = re.compile(r"\$\(|`|<\(|>\(")


def _tokenize(command: str) -> list[str] | None:
    """Shell-ish tokens with operators kept separate; None if unparseable."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return None


def _segment_command(tokens: list[str]) -> str:
    """The command a segment invokes, ignoring wrapper prefixes.

    `sudo git commit …` and `FOO=bar git commit …` both invoke git.
    """
    for token in tokens:
        base = token.rsplit("/", 1)[-1]
        if base in _COMMAND_PREFIXES:
            continue
        name, sep, _ = token.partition("=")
        if sep and not name.startswith("-"):
            continue  # VAR=value assignment prefix, not the command
        return base
    return ""


def _strip_segment(tokens: list[str]) -> list[str]:
    """Drop message-flag arguments, but only for commands that take them."""
    if _segment_command(tokens) not in MESSAGE_COMMANDS:
        return tokens

    kept: list[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            if _SUBSTITUTION.search(token):
                kept.append(token)  # not inert — inspect it
            continue

        if token in MESSAGE_FLAGS:
            skip_next = True
            continue

        # --message=... / --body=... in one token
        flag, sep, value = token.partition("=")
        if sep and flag in MESSAGE_FLAGS:
            if _SUBSTITUTION.search(value):
                kept.append(token)
            continue

        # -mfix typo — value attached to a short flag
        if len(token) > 2 and token[:2] in _ATTACHABLE_SHORT:
            if _SUBSTITUTION.search(token):
                kept.append(token)
            continue

        kept.append(token)

    return kept


def _strip_message_args(command: str) -> str:
    """Drop message-flag arguments from a shell command, keeping everything else.

    Returns the original command unchanged if it cannot be parsed — an
    unparseable command is scanned in full rather than trusted.
    """
    tokens = _tokenize(command)
    if tokens is None:
        return command  # unbalanced quotes: fail closed

    kept: list[str] = []
    segment: list[str] = []
    for token in tokens:
        if token in _SEGMENT_SEPARATORS:
            kept.extend(_strip_segment(segment))
            kept.append(token)
            segment = []
        else:
            segment.append(token)
    kept.extend(_strip_segment(segment))

    return " ".join(kept)


def _targets(tool: str, tool_input: dict) -> list[str]:
    """The strings worth inspecting for this tool."""
    if tool == "Read":
        return [str(tool_input.get("file_path", ""))]
    if tool == "Bash":
        return [_strip_message_args(str(tool_input.get("command", "")))]
    # Unknown tool: inspect nothing rather than guess and produce noise.
    return []


def check(tool: str, tool_input: dict) -> str | None:
    """Returns the offending fragment, or None when the call is fine."""
    for target in _targets(tool, tool_input):
        if not target:
            continue
        for pattern in SENSITIVE_PATHS:
            hit = pattern.search(target)
            if hit:
                return hit.group(0)
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # A hook that crashes must not block every tool call in the session.
        print(json.dumps({}))
        return 0

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    offender = check(tool, tool_input)
    if offender is None:
        print(json.dumps({}))
        return 0

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON.format(target=offender),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
