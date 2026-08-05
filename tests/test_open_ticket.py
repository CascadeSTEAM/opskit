"""Tests for bin/open-ticket.sh — fail-loud + --local behavior (issue #47).

A configured helpdesk must never silently degrade to a local placeholder;
local tracking is opt-in (--local) or for envs with `helpdesk: none`. Local
ids are single-prefixed and marked `<PREFIX>-LOCAL-<ts>`.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "open-ticket.sh"
# Ensure the script's `python3` (used to parse env.yml) has pyyaml.
VENV_BIN = os.path.dirname(sys.executable)

CONFIGURED = (
    "ticket:\n"
    "  prefix: TS\n"
    "  helpdesk: erpnext\n"
    "  helpdesk_endpoint: http://127.0.0.1:9\n"
    "  helpdesk_tenant: testtenant\n"
)
NOHELPDESK = "ticket:\n  prefix: TS\n  helpdesk: none\n"


def _root(tmp_path: Path, ticket_yaml: str) -> Path:
    root = tmp_path / "repo"
    (root / "environments" / "testenv").mkdir(parents=True)
    (root / ".env").write_text("ACTIVE_ENV=testenv\n")
    (root / "environments" / "testenv" / "env.yml").write_text(ticket_yaml)
    return root


def _run(root: Path, *args: str, extra_env: dict | None = None,
         pythonpath: str | None = None) -> subprocess.CompletedProcess:
    # Strip every credential this script might read so a developer's exported
    # environment cannot make a test pass (or fail) by accident.
    env = {k: v for k, v in os.environ.items() if not k.startswith("ERPNEXT_")}
    env["OPSKIT_ROOT"] = str(root)
    env["PATH"] = VENV_BIN + ":" + env["PATH"]
    if pythonpath:
        env["PYTHONPATH"] = pythonpath
    env.update(extra_env or {})
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env)


# A stub `requests` module placed on PYTHONPATH, so the script's own
# `import requests` picks it up. Lets the success paths — which auth method was
# used, what headers went out — be asserted with no network and no helpdesk.
STUB_REQUESTS = '''
import json as _json, os

_LOG = os.environ["STUB_LOG"]


def _record(entry):
    with open(_LOG, "a") as fh:
        fh.write(_json.dumps(entry) + "\\n")


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class Session:
    def __init__(self):
        self.headers = {}

    def post(self, url, json=None, timeout=None):
        _record({"url": url, "json": json, "headers": dict(self.headers)})
        if "/api/method/login" in url:
            return _Resp({"message": "Logged In"})
        return _Resp({"data": {"name": "0123"}})
'''


def _stub(tmp_path: Path):
    """(pythonpath, log_path) for a stubbed requests module."""
    libdir = tmp_path / "stublib"
    libdir.mkdir()
    (libdir / "requests.py").write_text(STUB_REQUESTS)
    return str(libdir), tmp_path / "calls.jsonl"


def _calls(log: Path) -> list:
    import json as _json
    if not log.exists():
        return []
    return [_json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _ticket(root: Path):
    f = root / ".current-ticket"
    return f.read_text().strip() if f.exists() else None


def test_configured_helpdesk_missing_credential_fails_loud(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    r = _run(root, "some work")
    assert r.returncode == 1
    assert "failed" in r.stderr.lower()
    assert _ticket(root) is None  # no fake ticket of record


def test_local_optin_writes_marked_single_prefix_id(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    r = _run(root, "--local", "some work")
    assert r.returncode == 0, r.stderr
    t = _ticket(root)
    assert re.fullmatch(r"TS-LOCAL-\d{12}", t or ""), t  # single prefix + marker


def test_local_requires_subject(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    r = _run(root, "--local")
    assert r.returncode == 1
    assert "requires a subject" in r.stderr


def test_no_helpdesk_env_uses_local(tmp_path):
    root = _root(tmp_path, NOHELPDESK)
    r = _run(root, "some work")
    assert r.returncode == 0, r.stderr
    assert re.fullmatch(r"TS-LOCAL-\d{12}", _ticket(root) or "")


def test_select_existing_ticket(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    r = _run(root, "CS-0022")
    assert r.returncode == 0, r.stderr
    assert _ticket(root) == "CS-0022"


def test_close_clears_ticket(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    _run(root, "CS-0022")
    r = _run(root, "close")
    assert r.returncode == 0, r.stderr
    assert _ticket(root) is None


# ── auth method selection (issue #91) ─────────────────────────────────────────
# The script used to hardcode a full-admin session login against a credential
# the repo never provisions, so the mandatory ticket gate could not be satisfied
# on a correctly configured workstation. Token auth for a least-privilege
# service account is now preferred; the password path is an explicit fallback.

TOKEN_ENV = {
    "ERPNEXT_API_KEY_TESTTENANT": "key123",
    "ERPNEXT_API_SECRET_TESTTENANT": "secret456",
}


def test_token_auth_is_used_and_creates_the_ticket(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    pp, log = _stub(tmp_path)
    r = _run(root, "some work", pythonpath=pp,
             extra_env={**TOKEN_ENV, "STUB_LOG": str(log)})
    assert r.returncode == 0, r.stderr
    assert _ticket(root) == "TS-0123"
    calls = _calls(log)
    assert not any("/api/method/login" in c["url"] for c in calls), \
        "token auth must not perform a session login"
    ticket_call = next(c for c in calls if "HD Ticket" in c["url"])
    assert ticket_call["headers"]["Authorization"] == "token key123:secret456"


def test_token_auth_preferred_over_password(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    pp, log = _stub(tmp_path)
    r = _run(root, "some work", pythonpath=pp, extra_env={
        **TOKEN_ENV,
        "ERPNEXT_ADMIN_PASSWORD_TESTTENANT": "adminpw",
        "STUB_LOG": str(log),
    })
    assert r.returncode == 0, r.stderr
    assert not any("/api/method/login" in c["url"] for c in _calls(log)), \
        "with both available, the least-privilege token must win"


def test_password_fallback_still_works(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    pp, log = _stub(tmp_path)
    r = _run(root, "some work", pythonpath=pp, extra_env={
        "ERPNEXT_ADMIN_PASSWORD_TESTTENANT": "adminpw",
        "STUB_LOG": str(log),
    })
    assert r.returncode == 0, r.stderr
    login = next(c for c in _calls(log) if "/api/method/login" in c["url"])
    assert login["json"]["pwd"] == "adminpw"
    ticket_call = next(c for c in _calls(log) if "HD Ticket" in c["url"])
    assert "Authorization" not in ticket_call["headers"]


def test_admin_username_is_not_hardcoded(tmp_path):
    """Requiring the `Administrator` account for a routine write is backwards;
    the username must be overridable."""
    root = _root(tmp_path, CONFIGURED)
    pp, log = _stub(tmp_path)
    r = _run(root, "some work", pythonpath=pp, extra_env={
        "ERPNEXT_ADMIN_PASSWORD_TESTTENANT": "adminpw",
        "ERPNEXT_ADMIN_USER_TESTTENANT": "svc@example.test",
        "STUB_LOG": str(log),
    })
    assert r.returncode == 0, r.stderr
    login = next(c for c in _calls(log) if "/api/method/login" in c["url"])
    assert login["json"]["usr"] == "svc@example.test"


def test_missing_credential_names_both_methods(tmp_path):
    """The old message named only the password variable, pointing the operator
    at the wrong credential entirely."""
    root = _root(tmp_path, CONFIGURED)
    r = _run(root, "some work")
    assert r.returncode == 1
    assert "ERPNEXT_API_KEY_TESTTENANT" in r.stderr
    assert "ERPNEXT_API_SECRET_TESTTENANT" in r.stderr
    assert "ERPNEXT_ADMIN_PASSWORD_TESTTENANT" in r.stderr
    assert _ticket(root) is None


def test_untenanted_vars_are_accepted(tmp_path):
    """An env with no helpdesk_tenant should still authenticate."""
    root = _root(tmp_path, (
        "ticket:\n"
        "  prefix: TS\n"
        "  helpdesk: erpnext\n"
        "  helpdesk_endpoint: http://127.0.0.1:9\n"
    ))
    pp, log = _stub(tmp_path)
    r = _run(root, "some work", pythonpath=pp, extra_env={
        "ERPNEXT_API_KEY": "k", "ERPNEXT_API_SECRET": "s", "STUB_LOG": str(log),
    })
    assert r.returncode == 0, r.stderr
    assert _ticket(root) == "TS-0123"


# ── --help must not file a ticket (issue #120, ledger row 34) ──────────────────
# The first argument was taken as the ticket subject unconditionally, so
# `open-ticket.sh --help` ATTEMPTED A LIVE CREATE titled "--help" against the
# client helpdesk. It only failed when found because credentials happened to be
# absent. A flag that acts instead of describing is a trap anywhere; in a tool
# whose side effect lands on someone else's system it is worse — a junk ticket on
# a client helpdesk is visible to the client.

def test_help_prints_usage_and_files_nothing(tmp_path):
    root = _root(tmp_path, CONFIGURED)

    result = _run(root, "--help")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Usage" in result.stdout
    assert not (root / ".current-ticket").exists()
    # The give-away that it tried to create: the create path always announces it.
    assert "Creating ticket" not in result.stdout


def test_short_help_flag_behaves_the_same(tmp_path):
    root = _root(tmp_path, CONFIGURED)

    result = _run(root, "-h")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Usage" in result.stdout
    assert not (root / ".current-ticket").exists()


def test_an_unknown_flag_is_refused_rather_than_filed(tmp_path):
    """The general fix: --help was one instance of 'a typo becomes a subject'."""
    root = _root(tmp_path, CONFIGURED)

    result = _run(root, "--bogus")

    assert result.returncode == 2
    assert "Refusing to treat" in result.stderr
    assert not (root / ".current-ticket").exists()


def test_the_refusal_shows_how_to_pass_a_dash_leading_subject(tmp_path):
    root = _root(tmp_path, CONFIGURED)

    result = _run(root, "--bogus")

    assert "-- " in result.stderr


def test_a_genuine_dash_leading_subject_works_after_a_separator(tmp_path):
    root = _root(tmp_path, NOHELPDESK)

    result = _run(root, "--local", "--", "-weird subject")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / ".current-ticket").exists()


def test_an_ordinary_subject_is_unaffected(tmp_path):
    root = _root(tmp_path, NOHELPDESK)

    result = _run(root, "--local", "a normal subject")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / ".current-ticket").exists()


def test_close_is_unaffected(tmp_path):
    root = _root(tmp_path, NOHELPDESK)
    _run(root, "--local", "something")

    result = _run(root, "close")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / ".current-ticket").exists()


def test_no_arguments_still_shows_the_current_ticket(tmp_path):
    root = _root(tmp_path, NOHELPDESK)

    result = _run(root)

    assert result.returncode == 0, result.stdout + result.stderr
