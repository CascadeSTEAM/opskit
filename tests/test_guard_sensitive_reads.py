"""Tests for bin/guard-sensitive-reads.py — the PreToolUse credential guard (#160).

A review workflow subagent read /etc/shadow and echoed it into a script. Agent
definitions could not have stopped it: the built-in workflow spawns default-tool
agents and never reads agents/*.md. A PreToolUse hook binds regardless of which
agent is running, which is why the guard lives here.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "bin" / "guard-sensitive-reads.py"

spec = importlib.util.spec_from_file_location("guard_sensitive_reads", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


DENIED_READS = [
    "/etc/shadow",
    "/etc/shadow-",
    "/etc/gshadow",
    "/etc/sudoers",
    "/home/someone/.ssh/id_ed25519",
    "/home/someone/.aws/credentials",
    "/home/someone/.kube/config",
    "/home/someone/.cache/opskit/bw-session",
    "/repo/.client-tokens",
]

ALLOWED_READS = [
    "/repo/bin/mcp-run.sh",
    "/repo/tests/test_secret_scan.py",
    "/etc/hosts",
    "/etc/os-release",
    "/home/someone/.ssh/id_ed25519.pub",   # public half is not a secret
    "/home/someone/Projects/other/README.md",
]


@pytest.mark.parametrize("path", DENIED_READS)
def test_credential_reads_are_denied(path):
    assert guard.check("Read", {"file_path": path}) is not None, path


@pytest.mark.parametrize("path", ALLOWED_READS)
def test_ordinary_reads_are_allowed(path):
    """A guard that fires on ordinary work gets disabled — deliberately narrow:
    credential stores, not "anything outside the repo"."""
    assert guard.check("Read", {"file_path": path}) is None, path


@pytest.mark.parametrize("command", [
    "cat /etc/shadow",
    "sudo cat /etc/shadow | head",
    "grep root /etc/gshadow",
    "cp ~/.ssh/id_rsa /tmp/x",
    "cat ~/.cache/opskit/bw-session",
])
def test_credential_reads_via_bash_are_denied(command):
    """The actual incident went through a shell command, not the Read tool."""
    assert guard.check("Bash", {"command": command}) is not None, command


@pytest.mark.parametrize("command", [
    "make test",
    "git log --oneline -5",
    "shellcheck bin/mcp-run.sh",
    "cat /etc/os-release",
])
def test_ordinary_commands_are_allowed(command):
    assert guard.check("Bash", {"command": command}) is None, command


def test_unknown_tools_are_not_second_guessed():
    assert guard.check("Glob", {"pattern": "/etc/shadow"}) is None


def _run(payload: dict) -> dict:
    r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout or "{}")


def test_hook_emits_a_deny_decision():
    out = _run({"tool_name": "Read", "tool_input": {"file_path": "/etc/shadow"}})

    hook = out["hookSpecificOutput"]
    assert hook["hookEventName"] == "PreToolUse"
    assert hook["permissionDecision"] == "deny"
    assert "credential store" in hook["permissionDecisionReason"]


def test_hook_stays_silent_on_ordinary_calls():
    out = _run({"tool_name": "Read", "tool_input": {"file_path": "/repo/README.md"}})

    assert out == {}


def test_malformed_payload_does_not_block_the_session():
    """A hook that crashes would deny every tool call in the session — worse
    than the risk it guards against."""
    r = subprocess.run([sys.executable, str(GUARD)], input="not json",
                       capture_output=True, text=True)

    assert r.returncode == 0
    assert json.loads(r.stdout or "{}") == {}


def test_the_incident_itself_is_blocked():
    """The exact shape observed: a subagent reading the password hash store and
    echoing it into a script it then ran."""
    assert guard.check("Bash", {
        "command": 'echo "$(cat /etc/shadow)" > /tmp/probe.sh'
    }) is not None


# ── message arguments are text, not reads (opskit #169) ──────────────────────
# Observed live in the first session with the hook wired: a `git commit` whose
# *message* documented the guard by naming a guarded path was denied. The
# scanner matched the path string anywhere in the command, including positions
# where nothing is opened. A guard that fires when you document the guard is
# exactly the "fires on ordinary work" failure mode that gets guards disabled.
#
# The fix is narrow on purpose, and both lists matter: dropping message text
# must not open a hole, so everything below that CAN cause a read still denies.

SHADOW = "/etc/" + "shadow"

MESSAGE_ONLY_MENTIONS = [
    # the reported reproducer
    f'git commit -m "deny reads of {SHADOW}"',
    "git commit -m 'document the .client-tokens guard'",
    'git commit --message="explain why ~/.ssh/id_ed25519 is denied"',
    f'git commit -a -m "note: /etc/sudoers stays unreadable"',
    f'gh issue create --title "guard denies {SHADOW}" --body "as designed"',
    'gh pr comment 1 --body "the .aws/credentials pattern is intentional"',
]

STILL_DENIED_DESPITE_A_MESSAGE_FLAG = [
    # a message built by running a command really does read the file
    f'git commit -m "$(cat {SHADOW})"',
    f'git commit -m "`cat {SHADOW}`"',
    'git commit --message="$(cat /repo/.client-tokens)"',
    # -F names a file the command opens; it is not a message flag
    f"git commit -F {SHADOW}",
    # a message argument must not cloak a second command
    f'git commit -m "clean subject" && cat {SHADOW}',
    f'git commit -m "clean subject"; cat {SHADOW} > /tmp/x',
    # the flag appearing later must not swallow an earlier real read
    f"cat {SHADOW} | git commit -m 'x'",
]

# The review of #169 caught these: -m, -b and -t are argument-less BOOLEANS in
# plenty of tools, where the next token is the file being read, not a message.
# Skipping it there hands out one-line exfiltration (`od -b <store>` dumps the
# whole file). So the strip is scoped to the commands that take these flags as
# messages, per segment — a git message earlier in the line must not license
# skipping in a later command.
BOOLEAN_FLAG_LOOKALIKES = [
    f"sort -m {SHADOW}",            # -m/--merge: prints the file verbatim
    f"sort -m {SHADOW} -o /tmp/out",
    f"sort -b {SHADOW}",            # -b/--ignore-leading-blanks
    f"diff -b {SHADOW} /etc/hosts",  # -b/--ignore-space-change
    f"od -b {SHADOW}",              # -b: octal dump of every byte
    f"column -t {SHADOW}",          # -t: table mode, reprints the file
    f"tar -t {SHADOW}",
    # a real message earlier must not license skipping in a later segment
    f'git commit -m "x" && sort -m {SHADOW}',
    f'git commit -m "x"; od -b {SHADOW}',
    f'gh pr comment 1 --body "note" && diff -b {SHADOW} /etc/hosts',
    # wrapper prefixes must not launder a non-message command
    f"sudo sort -m {SHADOW}",
    f"env od -b {SHADOW}",
]

MORE_MESSAGE_MENTIONS = [
    f'git commit -m"attached value: {SHADOW}"',   # value attached to -m
    f'sudo git commit -m "about {SHADOW}"',       # wrapper prefix, real git
    f'git commit -m "first" -m "second: {SHADOW}"',
]


@pytest.mark.parametrize("command", MESSAGE_ONLY_MENTIONS)
def test_naming_a_guarded_path_in_a_message_is_allowed(command):
    assert guard.check("Bash", {"command": command}) is None, command


@pytest.mark.parametrize("command", MORE_MESSAGE_MENTIONS)
def test_attached_values_and_wrapper_prefixes_are_still_messages(command):
    assert guard.check("Bash", {"command": command}) is None, command


@pytest.mark.parametrize("command", STILL_DENIED_DESPITE_A_MESSAGE_FLAG)
def test_a_message_flag_does_not_become_a_bypass(command):
    assert guard.check("Bash", {"command": command}) is not None, command


@pytest.mark.parametrize("command", BOOLEAN_FLAG_LOOKALIKES)
def test_boolean_flags_in_other_tools_are_not_message_flags(command):
    """`od -b <credential store>` dumps the file. The strip must be scoped to
    commands where these flags actually take a message, and scoped per segment
    so an earlier git message cannot license a later command."""
    assert guard.check("Bash", {"command": command}) is not None, command


def test_the_command_scope_is_what_makes_the_strip_safe():
    """Same flag, same following token — only the command differs."""
    assert guard._strip_message_args(f"git commit -m {SHADOW}") == "git commit"
    assert SHADOW in guard._strip_message_args(f"sort -m {SHADOW}")


def test_an_unparseable_command_is_scanned_in_full():
    """Unbalanced quotes must fail closed, not fall through unchecked."""
    assert guard.check("Bash", {"command": f'cat {SHADOW} "unclosed'}) is not None


def test_stripping_leaves_the_rest_of_the_command_intact():
    stripped = guard._strip_message_args('git commit -m "msg" && ls /tmp')
    assert "msg" not in stripped
    assert "ls" in stripped and "/tmp" in stripped
