"""Tests for bin/vikunja-manage-user.py (opskit issues #402, #404).

Everything here is offline: subprocess.run is replaced with a fake `run`
callable that records the argv/stdin it was given and returns a canned
CompletedProcess-shaped result -- no network, no ssh, no live Vikunja host,
ever. The module is loaded fresh per test via importlib (mirrors
tests/test_vikunja_mcp_server.py) because the file lives at
bin/vikunja-manage-user.py, not an importable package name.

Coverage focus:
  - tenant/exec-config resolution: unknown tenant, missing 'exec' block,
    missing individual exec keys -- all readable errors, no subprocess call
  - create: argv shape (ssh -> pct exec -> sudo -u -> binary), shell-quoting
    of username/email against injection (opskit #402 review finding),
    password over stdin never argv, verify word-boundary matching (not a
    substring test), --admin sequencing after a successful create only
  - id resolution (#404): a numeric identifier is used as-is; a username
    resolves via `user list` (zero/ambiguous matches are an error, never a
    guess) -- shared by update/enable/disable/delete/reset-password
  - update/enable/disable/delete/reset-password: correct upstream flags,
    resolve-before-act ordering, delete/reset-password default to the safe
    email-flow (upstream's own default) and only act immediately with
    --now/--direct, whose password (when generated) also travels over
    stdin, never argv
  - set-admin: accepts a username or id directly (the one exception to
    id-only), --admin/--no-admin are mutually exclusive
"""

import importlib.util
import shlex
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "vikunja-manage-user.py"


def load_module():
    spec = importlib.util.spec_from_file_location("vikunja_manage_user_under_test", SCRIPT)
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


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def test_list_users_returns_raw_output(mod):
    run = fake_run([completed(0, stdout=b"id  username\n1   alice\n")])
    result = mod.list_users(TENANT, run=run)

    assert result["raw"] == "id  username\n1   alice"
    remote_cmd = run.calls[0]["argv"][-1]
    assert "user list" in remote_cmd


def test_list_users_failure_is_surfaced(mod):
    run = fake_run([completed(1, stderr=b"connection refused")])
    with pytest.raises(RuntimeError, match="connection refused"):
        mod.list_users(TENANT, run=run)


# ---------------------------------------------------------------------------
# _resolve_user_id (#404) -- shared by update/enable/disable/delete/reset-password
# ---------------------------------------------------------------------------

def test_numeric_identifier_is_used_as_is_no_list_call(mod):
    run = fake_run([completed()])
    exec_cfg = EXEC_CFG
    user_id = mod._resolve_user_id(exec_cfg, "42", run=run)

    assert user_id == "42"
    run.assert_not_called()


def test_username_resolves_to_id_via_user_list(mod):
    run = fake_run([completed(0, stdout=b"id  username\n7   alice\n")])
    user_id = mod._resolve_user_id(EXEC_CFG, "alice", run=run)

    assert user_id == "7"


def test_username_resolves_across_non_whitespace_delimiters(mod):
    # `user list`'s output format isn't documented -- tolerate comma/pipe
    # separated rows too, not just whitespace tables (opskit #404).
    run = fake_run([completed(0, stdout=b"id,username\n7,alice\n")])
    user_id = mod._resolve_user_id(EXEC_CFG, "alice", run=run)

    assert user_id == "7"


def test_unknown_username_resolution_is_an_error(mod):
    run = fake_run([completed(0, stdout=b"id  username\n7   bob\n")])
    with pytest.raises(LookupError, match="no user found"):
        mod._resolve_user_id(EXEC_CFG, "alice", run=run)


def test_ambiguous_username_resolution_is_an_error_never_a_guess(mod):
    run = fake_run([completed(0, stdout=b"id  username\n7   alice\n9   alice\n")])
    with pytest.raises(LookupError, match="ambiguous"):
        mod._resolve_user_id(EXEC_CFG, "alice", run=run)


def test_resolution_substring_does_not_false_positive(mod):
    run = fake_run([completed(0, stdout=b"id  username\n7   alice\n")])
    with pytest.raises(LookupError, match="no user found"):
        mod._resolve_user_id(EXEC_CFG, "ali", run=run)


def test_list_failure_during_resolution_is_surfaced(mod):
    run = fake_run([completed(1, stderr=b"boom")])
    with pytest.raises(RuntimeError, match="boom"):
        mod._resolve_user_id(EXEC_CFG, "alice", run=run)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

def test_update_requires_at_least_one_field(mod):
    run = fake_run([completed()])
    with pytest.raises(ValueError, match="at least one"):
        mod.update_user(TENANT, "alice", run=run)
    run.assert_not_called()


def test_update_resolves_username_then_updates_by_id(mod):
    run = fake_run([
        completed(0, stdout=b"id  username\n7   alice\n"),
        completed(0),
    ])
    result = mod.update_user(TENANT, "alice", email="new@example.org", run=run)

    assert result == {"tenant": TENANT, "user_id": "7", "updated": True}
    remote_cmd = run.calls[1]["argv"][-1]
    assert remote_cmd.endswith("user update 7 -e new@example.org")  # no -u: username wasn't given


def test_update_by_numeric_id_skips_resolution(mod):
    run = fake_run([completed(0)])
    mod.update_user(TENANT, "7", username="newname", run=run)

    assert run.call_count == 1  # no `user list` call needed
    remote_cmd = run.calls[0]["argv"][-1]
    assert "user update 7" in remote_cmd
    assert "-u newname" in remote_cmd


def test_update_failure_is_surfaced(mod):
    run = fake_run([completed(1, stderr=b"boom")])
    with pytest.raises(RuntimeError, match="boom"):
        mod.update_user(TENANT, "7", username="newname", run=run)


# ---------------------------------------------------------------------------
# enable / disable (user change-status)
# ---------------------------------------------------------------------------

def test_disable_by_username(mod):
    run = fake_run([
        completed(0, stdout=b"id  username\n7   alice\n"),
        completed(0),
    ])
    result = mod.set_status(TENANT, "alice", False, run=run)

    assert result == {"tenant": TENANT, "user_id": "7", "enabled": False}
    remote_cmd = run.calls[1]["argv"][-1]
    assert "user change-status 7" in remote_cmd
    assert "--disable" in remote_cmd


def test_enable_by_id(mod):
    run = fake_run([completed(0)])
    result = mod.set_status(TENANT, "7", True, run=run)

    assert result["enabled"] is True
    remote_cmd = run.calls[0]["argv"][-1]
    assert "--enable" in remote_cmd


def test_change_status_failure_is_surfaced(mod):
    run = fake_run([completed(1, stderr=b"boom")])
    with pytest.raises(RuntimeError, match="boom"):
        mod.set_status(TENANT, "7", True, run=run)


# ---------------------------------------------------------------------------
# delete -- upstream defaults to emailing a confirmation link, never deletes
# immediately without --now
# ---------------------------------------------------------------------------

def test_delete_without_now_is_email_confirmation_mode(mod):
    run = fake_run([completed(0)])
    result = mod.delete_user(TENANT, "7", now=False, run=run)

    assert result["mode"] == "email-confirmation-requested"
    remote_cmd = run.calls[0]["argv"][-1]
    assert "user delete 7" in remote_cmd
    assert "--now" not in remote_cmd


def test_delete_with_now_is_immediate_mode(mod):
    run = fake_run([completed(0)])
    result = mod.delete_user(TENANT, "7", now=True, run=run)

    assert result["mode"] == "immediate"
    remote_cmd = run.calls[0]["argv"][-1]
    assert "--now" in remote_cmd


def test_delete_resolves_username_first(mod):
    run = fake_run([
        completed(0, stdout=b"id  username\n7   alice\n"),
        completed(0),
    ])
    result = mod.delete_user(TENANT, "alice", now=False, run=run)

    assert result["user_id"] == "7"


def test_delete_failure_is_surfaced(mod):
    run = fake_run([completed(1, stderr=b"boom")])
    with pytest.raises(RuntimeError, match="boom"):
        mod.delete_user(TENANT, "7", now=True, run=run)


# ---------------------------------------------------------------------------
# reset-password -- upstream defaults to emailing a reset link
# ---------------------------------------------------------------------------

def test_reset_password_without_direct_is_email_mode_no_password_sent(mod):
    run = fake_run([completed(0)])
    result = mod.reset_password(TENANT, "7", direct=False, run=run)

    assert result["mode"] == "email-reset-link"
    assert "password" not in result
    call = run.calls[0]
    assert call["input"] is None
    remote_cmd = call["argv"][-1]
    assert "user reset-password 7" in remote_cmd
    assert "--direct" not in remote_cmd


def test_reset_password_direct_generates_and_sends_password_over_stdin(mod):
    run = fake_run([completed(0)])
    result = mod.reset_password(TENANT, "7", direct=True, run=run)

    assert result["mode"] == "direct"
    assert result["password"]
    call = run.calls[0]
    assert result["password"].encode() in call["input"]
    assert result["password"] not in call["argv"][-1]
    assert "--direct" in call["argv"][-1]


def test_reset_password_direct_with_explicit_password(mod):
    run = fake_run([completed(0)])
    result = mod.reset_password(TENANT, "7", direct=True, password="givenpw", run=run)

    assert result["password"] == "givenpw"
    assert b"givenpw" in run.calls[0]["input"]


def test_reset_password_resolves_username_first(mod):
    run = fake_run([
        completed(0, stdout=b"id  username\n7   alice\n"),
        completed(0),
    ])
    result = mod.reset_password(TENANT, "alice", direct=False, run=run)

    assert result["user_id"] == "7"


def test_reset_password_failure_is_surfaced(mod):
    run = fake_run([completed(1, stderr=b"boom")])
    with pytest.raises(RuntimeError, match="boom"):
        mod.reset_password(TENANT, "7", direct=True, run=run)


# ---------------------------------------------------------------------------
# set-admin -- the one action that accepts a username OR id directly
# ---------------------------------------------------------------------------

def test_set_admin_accepts_username_directly_no_resolution(mod):
    run = fake_run([completed(0)])
    result = mod.set_admin(TENANT, "alice", True, run=run)

    assert run.call_count == 1  # no `user list` call
    assert result == {"tenant": TENANT, "identifier": "alice", "admin": True}
    remote_cmd = run.calls[0]["argv"][-1]
    assert "user set-admin alice --admin" in remote_cmd


def test_set_admin_no_admin_demotes(mod):
    run = fake_run([completed(0)])
    mod.set_admin(TENANT, "alice", False, run=run)

    remote_cmd = run.calls[0]["argv"][-1]
    assert "--no-admin" in remote_cmd
    assert "--admin" not in remote_cmd


def test_set_admin_failure_is_surfaced_readably(mod):
    # e.g. no Vikunja Pro license -- a normal error, not a crash.
    run = fake_run([completed(1, stderr=b"this feature requires Vikunja Pro")])
    with pytest.raises(RuntimeError, match="Vikunja Pro"):
        mod.set_admin(TENANT, "alice", True, run=run)
