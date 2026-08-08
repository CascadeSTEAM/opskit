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
