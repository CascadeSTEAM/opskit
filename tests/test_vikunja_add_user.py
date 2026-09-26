"""Tests for bin/vikunja-add-user.py (opskit issue #402).

Everything here is offline: subprocess.run is replaced with a fake `run`
callable that records the argv/stdin it was given and returns a canned
CompletedProcess-shaped result -- no network, no ssh, no live Vikunja host,
ever. The module is loaded fresh per test via importlib (mirrors
tests/test_vikunja_mcp_server.py) because the file lives at
bin/vikunja-add-user.py, not an importable package name.

Coverage focus:
  - tenant/exec-config resolution: unknown tenant, missing 'exec' block,
    missing individual exec keys -- all readable errors, no subprocess call
  - the create command's argv shape (ssh -> pct exec -> sudo -u -> binary)
    and that the password travels over stdin, never argv (opskit #402 --
    same fix class as the vikunja-ticket curl-bearer-token argv exposure)
  - a non-zero create exit surfaces the remote stderr and never calls
    set-admin or list afterward
  - --admin runs set-admin only after a successful create, and its own
    failure is a warning on a success envelope, not a bare error (the user
    account already exists, so it must not read as "nothing happened")
  - the reported result's password is the one actually sent over stdin,
    not a re-generated value
"""

import importlib.util
import shlex
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "vikunja-add-user.py"


def load_module():
    spec = importlib.util.spec_from_file_location("vikunja_add_user_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TENANT = "client1"
EXEC_CFG = {
    "ssh_host": "pve-test",
    "ctid": 999,
    "exec_user": "vikunja",
    "binary": "/opt/vikunja/vikunja",
    "config_path": "/opt/vikunja/config.yaml",
}


@pytest.fixture
def isolated_tenants_file(tmp_path, monkeypatch):
    fixture_file = tmp_path / "tenants-vikunja.local.json"
    fixture_file.write_text(__import__("json").dumps({
        TENANT: {"base_url": "https://vikunja.example.org", "exec": EXEC_CFG},
        "no-exec": {"base_url": "https://other.example.org"},
    }))
    monkeypatch.setenv("VIKUNJA_TENANTS_FILE", str(fixture_file))
    return fixture_file


@pytest.fixture
def mod(isolated_tenants_file):
    return load_module()


def completed(returncode=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(args=["ssh"], returncode=returncode, stdout=stdout, stderr=stderr)


def fake_run(responses):
    """Returns a MagicMock `run` double that yields `responses` in call order,
    repeating the last one once exhausted, and records every call."""
    calls = []

    def _run(argv, input=None, capture_output=None, **kwargs):
        calls.append({"argv": argv, "input": input})
        idx = min(len(calls) - 1, len(responses) - 1)
        return responses[idx]

    m = MagicMock(side_effect=_run)
    m.calls = calls
    return m


# ---------------------------------------------------------------------------
# Tenant / exec-config resolution -- no subprocess call for any of these
# ---------------------------------------------------------------------------

def test_unknown_tenant_is_a_readable_error(mod):
    run = fake_run([completed()])
    with pytest.raises(ValueError, match="unknown tenant"):
        mod.create_user("ghost", "alice", "alice@example.org", "pw", False, run=run)
    run.assert_not_called()


def test_tenant_without_exec_block_is_a_readable_error(mod):
    run = fake_run([completed()])
    with pytest.raises(ValueError, match="no 'exec' block"):
        mod.create_user("no-exec", "alice", "alice@example.org", "pw", False, run=run)
    run.assert_not_called()


def test_incomplete_exec_block_names_missing_keys(mod, monkeypatch, tmp_path):
    import json
    fixture_file = tmp_path / "tenants-vikunja.local.json"
    fixture_file.write_text(json.dumps({
        TENANT: {"exec": {"ssh_host": "pve-test"}},
    }))
    monkeypatch.setenv("VIKUNJA_TENANTS_FILE", str(fixture_file))
    reloaded = load_module()

    run = fake_run([completed()])
    with pytest.raises(ValueError, match="ctid"):
        reloaded.create_user(TENANT, "alice", "alice@example.org", "pw", False, run=run)
    run.assert_not_called()


# ---------------------------------------------------------------------------
# Argv shape / password-over-stdin
# ---------------------------------------------------------------------------

def test_create_command_argv_shape(mod):
    run = fake_run([completed(0), completed(0, stdout=b"alice\n")])
    mod.create_user(TENANT, "alice", "alice@example.org", "s3cret", False, run=run)

    create_call = run.calls[0]
    argv = create_call["argv"]
    assert argv[0] == "ssh"
    assert "pve-test" in argv
    remote_cmd = argv[-1]
    assert "pct exec 999" in remote_cmd
    assert "sudo -u vikunja" in remote_cmd
    assert "/opt/vikunja/vikunja" in remote_cmd
    assert "user create" in remote_cmd
    assert "--config /opt/vikunja/config.yaml" in remote_cmd
    assert "-u alice" in remote_cmd
    assert "-e alice@example.org" in remote_cmd


def test_malicious_username_is_shell_quoted_not_injected(mod):
    # ssh hands its remote-command string to the target's own shell -- a
    # username containing shell metacharacters must come out as a single
    # inert argument, not break out into a second command (opskit #402
    # review finding).
    run = fake_run([completed(0), completed(0)])
    evil = "alice; rm -rf /"
    mod.create_user(TENANT, evil, "alice@example.org", "pw", False, run=run)

    remote_cmd = run.calls[0]["argv"][-1]
    tokens = shlex.split(remote_cmd)
    assert evil in tokens
    assert "rm" not in tokens  # would appear as its own token if unescaped


def test_email_with_shell_metacharacters_is_shell_quoted(mod):
    run = fake_run([completed(0), completed(0)])
    evil_email = "a@example.org`whoami`"
    mod.create_user(TENANT, "alice", evil_email, "pw", False, run=run)

    remote_cmd = run.calls[0]["argv"][-1]
    assert evil_email in shlex.split(remote_cmd)


def test_password_travels_over_stdin_never_argv(mod):
    run = fake_run([completed(0), completed(0)])
    mod.create_user(TENANT, "alice", "alice@example.org", "s3cret-value", False, run=run)

    create_call = run.calls[0]
    assert b"s3cret-value" in create_call["input"]
    assert "s3cret-value" not in " ".join(create_call["argv"])


# ---------------------------------------------------------------------------
# Failure surfacing
# ---------------------------------------------------------------------------

def test_create_failure_surfaces_remote_stderr_and_stops(mod):
    run = fake_run([completed(1, stderr=b"user already exists")])
    with pytest.raises(RuntimeError, match="user already exists"):
        mod.create_user(TENANT, "alice", "alice@example.org", "pw", False, run=run)
    assert run.call_count == 1  # never proceeded to list/set-admin


# ---------------------------------------------------------------------------
# Verification (user list)
# ---------------------------------------------------------------------------

def test_successful_create_is_verified_against_user_list(mod):
    run = fake_run([completed(0), completed(0, stdout=b"id  username\n1   alice\n")])
    result = mod.create_user(TENANT, "alice", "alice@example.org", "pw", False, run=run)

    assert result["created"] is True
    assert result["verified"] is True
    assert result["password"] == "pw"


def test_username_absent_from_list_is_not_verified(mod):
    run = fake_run([completed(0), completed(0, stdout=b"id  username\n1   bob\n")])
    result = mod.create_user(TENANT, "alice", "alice@example.org", "pw", False, run=run)

    assert result["created"] is True
    assert result["verified"] is False


def test_verify_does_not_false_positive_on_substring_match(mod):
    # "ali" is a substring of "alice" -- a plain `in` check would wrongly
    # report "ali" as verified off the back of an unrelated existing user
    # (opskit #402 review finding).
    run = fake_run([completed(0), completed(0, stdout=b"id  username\n1   alice\n")])
    result = mod.create_user(TENANT, "ali", "ali@example.org", "pw", False, run=run)

    assert result["verified"] is False


# ---------------------------------------------------------------------------
# --admin
# ---------------------------------------------------------------------------

def test_admin_flag_runs_set_admin_after_successful_create(mod):
    run = fake_run([completed(0), completed(0, stdout=b"alice\n"), completed(0)])
    result = mod.create_user(TENANT, "alice", "alice@example.org", "pw", True, run=run)

    assert run.call_count == 3
    set_admin_call = run.calls[2]["argv"][-1]
    assert "user set-admin alice --admin" in set_admin_call
    assert result["admin"] is True
    assert "warnings" not in result


def test_admin_flag_failure_is_a_warning_not_a_bare_error(mod):
    run = fake_run([
        completed(0),
        completed(0, stdout=b"alice\n"),
        completed(1, stderr=b"boom"),
    ])
    result = mod.create_user(TENANT, "alice", "alice@example.org", "pw", True, run=run)

    assert result["created"] is True
    assert "admin" not in result
    assert any("boom" in w for w in result["warnings"])


def test_admin_not_attempted_when_create_fails(mod):
    run = fake_run([completed(1, stderr="nope".encode())])
    with pytest.raises(RuntimeError):
        mod.create_user(TENANT, "alice", "alice@example.org", "pw", True, run=run)
    assert run.call_count == 1
