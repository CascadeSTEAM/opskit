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


def _targets(tool: str, tool_input: dict) -> list[str]:
    """The strings worth inspecting for this tool."""
    if tool == "Read":
        return [str(tool_input.get("file_path", ""))]
    if tool == "Bash":
        return [str(tool_input.get("command", ""))]
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
