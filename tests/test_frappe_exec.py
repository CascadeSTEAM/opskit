"""Tests for bin/frappe-exec.py — the sanctioned Path B execution wrapper (issue #71).

Everything here is offline: subprocess.run is monkeypatched so no `ssh` /
`docker` / bench process is ever actually invoked. The module is loaded fresh
per test via importlib so OPSKIT_ROOT (read at module-exec time) can vary
between tests without import caching getting in the way.
"""

import importlib.util
import io
import json
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "frappe-exec.py"


def load_module():
    spec = importlib.util.spec_from_file_location("frappe_exec_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fe(monkeypatch, tmp_path):
    """Fresh module instance with OPSKIT_ROOT pointed at an isolated tmp repo."""
    monkeypatch.setenv("OPSKIT_ROOT", str(tmp_path))
    return load_module()


def _fake_completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=["fake"], returncode=returncode, stdout=stdout, stderr=stderr)


class TestBuildCommand:
    def test_never_uses_docker_cp(self, fe):
        cmd = fe.build_command("mycontainer", "myssh", "/venv/bin/python", "/sites")
        assert "cp" not in cmd
        assert not any("cp" == part for part in cmd)

    def test_uses_venv_python_not_bench_console(self, fe):
        cmd = fe.build_command("mycontainer", "", "/venv/bin/python", "/sites")
        assert "bench" not in cmd
        assert "console" not in cmd
        assert "/venv/bin/python" in cmd
        assert cmd[-1] == "-"  # streamed via stdin, never a file argument

    def test_streams_via_docker_exec_i(self, fe):
        cmd = fe.build_command("mycontainer", "", "/venv/bin/python", "/sites")
        assert cmd[:3] == ["docker", "exec", "-i"]
        assert "-w" in cmd and "/sites" in cmd

    def test_ssh_alias_wraps_docker_exec(self, fe):
        cmd = fe.build_command("mycontainer", "myhostalias", "/venv/bin/python", "/sites")
        assert cmd[0:2] == ["ssh", "myhostalias"]
        # The remote command is one already shell-quoted string (see
        # test_ssh_alias_quotes_hostile_values for why), not separate argv
        # elements -- ssh(1) would otherwise re-join separate elements with
        # spaces and hand them to a remote shell.
        assert len(cmd) == 3
        assert "docker" in cmd[2]

    def test_no_ssh_alias_runs_docker_directly(self, fe):
        cmd = fe.build_command("mycontainer", "", "/venv/bin/python", "/sites")
        assert cmd[0] == "docker"
        assert "ssh" not in cmd

    def test_ssh_alias_quotes_hostile_values(self, fe):
        """ssh(1): 'the arguments will be appended to the command, separated
        by spaces, before it is sent to the server to be executed' -- ssh
        joins trailing argv with plain spaces and a shell on the remote end
        parses the result. A container/cwd/venv_python value containing
        shell metacharacters must not be able to inject a second command."""
        evil_container = "good; touch /tmp/PWNED; echo x"
        cmd = fe.build_command(evil_container, "myhostalias", "/venv/bin/python", "/sites")
        assert cmd[0:2] == ["ssh", "myhostalias"]
        remote_string = cmd[2]

        # Simulate what ssh(1) does on the remote end: hand the string to a
        # POSIX shell. shlex (POSIX mode) is a faithful stand-in for that.
        parsed_back = shlex.split(remote_string)
        assert parsed_back == [
            "docker", "exec", "-i", "-w", "/sites",
            evil_container, "/venv/bin/python", "-",
        ]
        # The injected shell metacharacters must not appear unquoted/bare in
        # the string ssh will forward -- i.e. they must be wrapped in quotes.
        assert "'good; touch /tmp/PWNED; echo x'" in remote_string

    def test_no_ssh_alias_needs_no_quoting(self, fe):
        """Without --ssh-alias, subprocess.run gets the argv list directly
        (no shell=True, no remote shell) -- metacharacters in a value are
        just inert bytes in one argv element, never re-parsed."""
        evil_container = "good; touch /tmp/PWNED; echo x"
        cmd = fe.build_command(evil_container, "", "/venv/bin/python", "/sites")
        assert evil_container in cmd
        assert cmd == ["docker", "exec", "-i", "-w", "/sites", evil_container, "/venv/bin/python", "-"]


class TestBuildHarness:
    def test_harness_compiles(self, fe):
        src = fe.build_harness("mysite.local", "Administrator", "result = 1 + 1")
        compile(src, "<test>", "exec")  # raises SyntaxError if malformed

    def test_harness_embeds_script_safely_via_base64(self, fe):
        # A script containing quotes/newlines/backslashes must not corrupt the harness.
        tricky = 'result = "a\'b\\nc" + str([1, 2])\n# comment with "quotes"'
        src = fe.build_harness("site", "user", tricky)
        compile(src, "<test>", "exec")
        assert "frappe.init(site=" in src
        assert "frappe.connect()" in src
        assert "frappe.set_user(" in src
        assert "frappe.db.commit()" in src

    def test_harness_never_calls_bench_console(self, fe):
        src = fe.build_harness("site", "user", "result = None")
        assert "bench" not in src
        assert "console" not in src


class TestEnvelopeRoundTrip:
    """The whole point of the JSON envelope is that 0 / [] / "" / None must
    never be confused with "no output" or an error."""

    @pytest.mark.parametrize("falsy_result", [0, [], "", None, False, {}])
    def test_falsy_results_round_trip_unambiguously(self, fe, monkeypatch, tmp_path, capsys, falsy_result):
        remote_stdout = json.dumps({"ok": True, "result": falsy_result, "error": None})
        monkeypatch.setattr(fe.subprocess, "run", lambda *a, **k: _fake_completed(stdout=remote_stdout))

        script = tmp_path / "s.py"
        script.write_text("result = 'placeholder'")
        rc = fe.main(["--site", "s", "--container", "c", "--script", str(script)])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert out["result"] == falsy_result
        assert out["error"] is None


class TestDryRun:
    def test_print_mode_never_invokes_subprocess(self, fe, monkeypatch, tmp_path, capsys):
        def boom(*a, **k):
            raise AssertionError("subprocess.run must not be called in --print mode")

        monkeypatch.setattr(fe.subprocess, "run", boom)
        script = tmp_path / "s.py"
        script.write_text("result = 42")

        rc = fe.main([
            "--print", "--site", "s.local", "--container", "frappe1",
            "--ssh-alias", "dockerhost", "--script", str(script),
        ])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert out["error"] is None
        assert "cp" not in out["result"]["command"]
        assert out["result"]["site"] == "s.local"
        assert out["result"]["container"] == "frappe1"
        assert out["result"]["ssh_alias"] == "dockerhost"

    def test_print_mode_with_no_ssh_alias(self, fe, monkeypatch, tmp_path):
        monkeypatch.setattr(fe.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no")))
        script = tmp_path / "s.py"
        script.write_text("result = 1")
        rc = fe.main(["--print", "--site", "s", "--container", "c", "--script", str(script)])
        assert rc == 0


class TestConfigResolution:
    def test_missing_site_fails_before_any_subprocess(self, fe, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            fe.subprocess, "run",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")),
        )
        script = tmp_path / "s.py"
        script.write_text("result = 1")
        rc = fe.main(["--container", "c", "--script", str(script)])
        assert rc == 1
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False
        assert "site" in out["error"]

    def test_missing_container_fails(self, fe, tmp_path, capsys):
        script = tmp_path / "s.py"
        script.write_text("result = 1")
        rc = fe.main(["--site", "s", "--script", str(script)])
        assert rc == 1
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False
        assert "container" in out["error"]

    def test_env_yml_supplies_connection_details(self, monkeypatch, tmp_path, capsys):
        env_dir = tmp_path / "environments" / "testenv"
        env_dir.mkdir(parents=True)
        (env_dir / "env.yml").write_text(
            "frappe:\n"
            "  site: fromyaml.local\n"
            "  container: yaml-container\n"
            "  ssh_alias: yaml-ssh-alias\n"
        )
        (tmp_path / ".env").write_text("ACTIVE_ENV=testenv\n")
        monkeypatch.setenv("OPSKIT_ROOT", str(tmp_path))
        mod = load_module()

        script = tmp_path / "s.py"
        script.write_text("result = 1")
        rc = mod.main(["--print", "--script", str(script)])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["result"]["site"] == "fromyaml.local"
        assert out["result"]["container"] == "yaml-container"
        assert out["result"]["ssh_alias"] == "yaml-ssh-alias"

    def test_cli_flags_override_env_yml(self, monkeypatch, tmp_path, capsys):
        env_dir = tmp_path / "environments" / "testenv"
        env_dir.mkdir(parents=True)
        (env_dir / "env.yml").write_text(
            "frappe:\n  site: fromyaml.local\n  container: yaml-container\n"
        )
        (tmp_path / ".env").write_text("ACTIVE_ENV=testenv\n")
        monkeypatch.setenv("OPSKIT_ROOT", str(tmp_path))
        mod = load_module()

        script = tmp_path / "s.py"
        script.write_text("result = 1")
        rc = mod.main(["--print", "--site", "override.local", "--script", str(script)])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["result"]["site"] == "override.local"
        assert out["result"]["container"] == "yaml-container"


class TestRemoteFailureModes:
    def test_nonzero_exit_reported_as_failure(self, fe, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            fe.subprocess, "run",
            lambda *a, **k: _fake_completed(stderr="ssh: connect refused", returncode=255),
        )
        script = tmp_path / "s.py"
        script.write_text("result = 1")
        rc = fe.main(["--site", "s", "--container", "c", "--script", str(script)])
        assert rc == 1
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False
        assert "connect refused" in out["error"]

    def test_non_json_remote_output_reported_as_failure(self, fe, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(fe.subprocess, "run", lambda *a, **k: _fake_completed(stdout="not json at all"))
        script = tmp_path / "s.py"
        script.write_text("result = 1")
        rc = fe.main(["--site", "s", "--container", "c", "--script", str(script)])
        assert rc == 1
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False

    def test_remote_reported_error_propagates(self, fe, monkeypatch, tmp_path, capsys):
        remote_stdout = json.dumps({"ok": False, "result": None, "error": "DoesNotExistError: no HD Ticket 0099"})
        monkeypatch.setattr(fe.subprocess, "run", lambda *a, **k: _fake_completed(stdout=remote_stdout))
        script = tmp_path / "s.py"
        script.write_text("result = 1")
        rc = fe.main(["--site", "s", "--container", "c", "--script", str(script)])
        assert rc == 1
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False
        assert "0099" in out["error"]


class TestScriptInput:
    def test_reads_from_stdin_when_no_script_flag(self, fe, monkeypatch, capsys):
        monkeypatch.setattr(fe.sys, "stdin", io.StringIO("result = 7"))
        monkeypatch.setattr(fe.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
        rc = fe.main(["--print", "--site", "s", "--container", "c"])
        assert rc == 0

    def test_empty_script_fails(self, fe, monkeypatch, capsys):
        monkeypatch.setattr(fe.sys, "stdin", io.StringIO("   \n  "))
        rc = fe.main(["--print", "--site", "s", "--container", "c"])
        assert rc == 1
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False
        assert "empty" in out["error"]
