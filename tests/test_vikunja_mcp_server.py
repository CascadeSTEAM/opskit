"""Tests for mcp/vikunja-mcp-server.py (opskit issue #393).

Everything here is offline: VikunjaClient is replaced with a MagicMock double
(spec'd against the real class so a call to a nonexistent method fails
loudly) and `get_client` is monkeypatched to hand that double back -- no
network, no live Vikunja call, ever. The module is loaded fresh per test via
importlib (mirrors tests/test_erpnext_mcp_server.py) because the file lives
at mcp/vikunja-mcp-server.py, not an importable package name.

Coverage focus:
  - project resolution by name: exact match, default-project fallback, no
    match, and ambiguous match (must not create a task on ambiguity)
  - the token env var is per-tenant (VIKUNJA_<TENANT>_TOKEN) with an
    unsuffixed VIKUNJA_TOKEN fallback, and a missing token is an actionable
    error, never a raw traceback
  - the API's own error body is surfaced on an HTTP error, not swallowed
  - the reported URL is built from the tenant's configured base_url + the
    created task's id
  - opskit #396: priority range validation; assignee/label resolution by
    exact match (none/ambiguous is an error, before any task is created);
    a failure attaching an assignee/label *after* the task already exists
    is a warning on a success envelope, never a bare error (the task is
    real, so reporting only an error risks a duplicate-creating retry)
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mcp" / "vikunja-mcp-server.py"


def load_module():
    spec = importlib.util.spec_from_file_location("vikunja_mcp_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TENANT = "client1"  # the tenant key baked into the fixture below
BASE_URL = "https://vikunja.example.org"


@pytest.fixture
def isolated_tenants_file(tmp_path, monkeypatch):
    """Point VIKUNJA_TENANTS_FILE at a throwaway fixture file so the module
    (loaded fresh per test via `load_module`, below) never reads a
    developer's real, gitignored mcp/tenants-vikunja.local.json -- whether or
    not one exists, and regardless of what it contains (same defect class as
    opskit issue #76 for the erpnext server)."""
    fixture_file = tmp_path / "tenants-vikunja.local.json"
    fixture_file.write_text(json.dumps({
        TENANT: {"base_url": BASE_URL, "default_project": "Tickets"},
    }))
    monkeypatch.setenv("VIKUNJA_TENANTS_FILE", str(fixture_file))
    return fixture_file


@pytest.fixture
def mod(isolated_tenants_file):
    return load_module()


@pytest.fixture
def fake_client(mod):
    """A VikunjaClient double, spec'd so typos/renamed methods fail loudly.
    Individual tests configure .list_projects/.create_task as needed."""
    return MagicMock(spec=mod.VikunjaClient)


@pytest.fixture
def wire_client(mod, fake_client, monkeypatch):
    """Point get_client(tenant) at fake_client for every tenant."""
    monkeypatch.setattr(mod, "get_client", lambda tenant: fake_client)
    return fake_client


def http_error(status_code=400, body=None):
    resp = requests.Response()
    resp.status_code = status_code
    if body is not None:
        resp._content = json.dumps(body).encode("utf-8")
    return requests.HTTPError(response=resp)


# ---------------------------------------------------------------------------
# Basic validation -- no client call should happen for these
# ---------------------------------------------------------------------------

def test_invalid_tenant_returns_message(mod):
    result = mod.vikunja_create_task(tenant="nope", title="Task")
    assert "Invalid tenant" in result
    assert TENANT in result


def test_missing_title_returns_error(mod, wire_client):
    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="   "))
    assert "error" in result
    wire_client.list_projects.assert_not_called()
    wire_client.create_task.assert_not_called()


# ---------------------------------------------------------------------------
# Project resolution
# ---------------------------------------------------------------------------

def test_create_task_success_with_explicit_project(mod, wire_client):
    wire_client.list_projects.return_value = [
        {"id": 1, "title": "Tickets"},
        {"id": 2, "title": "Backlog"},
    ]
    wire_client.create_task.return_value = {"id": 42, "title": "Fix the thing"}

    result = json.loads(mod.vikunja_create_task(
        tenant=TENANT, title="Fix the thing", description="details", project="Backlog",
    ))

    wire_client.create_task.assert_called_once_with(
        2, "Fix the thing", "details", priority=None, due_date=None
    )
    assert result["url"] == f"{BASE_URL}/tasks/42"
    assert result["task"]["id"] == 42


def test_create_task_uses_default_project_when_omitted(mod, wire_client):
    wire_client.list_projects.return_value = [{"id": 1, "title": "Tickets"}]
    wire_client.create_task.return_value = {"id": 7}

    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="No project given"))

    wire_client.create_task.assert_called_once_with(
        1, "No project given", "", priority=None, due_date=None
    )
    assert result["url"] == f"{BASE_URL}/tasks/7"


def test_no_matching_project_returns_error(mod, wire_client):
    wire_client.list_projects.return_value = [{"id": 1, "title": "Backlog"}]

    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X", project="Ghost"))

    assert "error" in result
    assert "Ghost" in result["error"]
    wire_client.create_task.assert_not_called()


def test_ambiguous_project_match_does_not_create_task(mod, wire_client):
    wire_client.list_projects.return_value = [
        {"id": 1, "title": "Tickets"},
        {"id": 2, "title": "Tickets"},
    ]

    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X", project="Tickets"))

    assert "error" in result
    wire_client.create_task.assert_not_called()


# ---------------------------------------------------------------------------
# HTTP / credential failure surfacing
# ---------------------------------------------------------------------------

def test_api_error_body_is_surfaced(mod, wire_client):
    wire_client.list_projects.return_value = [{"id": 1, "title": "Tickets"}]
    wire_client.create_task.side_effect = http_error(400, {"message": "title too long"})

    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X", project="Tickets"))

    assert "error" in result
    assert "title too long" in result["error"]


def test_missing_token_env_var_is_actionable(mod):
    # No VIKUNJA_CLIENT1_TOKEN / VIKUNJA_TOKEN set -- get_client() itself must
    # fail with a message naming the exact env var, not a raw traceback.
    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X"))

    assert "error" in result
    assert "VIKUNJA_CLIENT1_TOKEN" in result["error"]


# ---------------------------------------------------------------------------
# Priority (opskit #396)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_priority", [-1, 6])
def test_invalid_priority_returns_error_before_any_call(mod, wire_client, bad_priority):
    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X", priority=bad_priority))

    assert "error" in result
    wire_client.list_projects.assert_not_called()
    wire_client.create_task.assert_not_called()


def test_priority_and_due_date_are_passed_through(mod, wire_client):
    wire_client.list_projects.return_value = [{"id": 1, "title": "Tickets"}]
    wire_client.create_task.return_value = {"id": 8}

    mod.vikunja_create_task(
        tenant=TENANT, title="X", priority=3, due_date="2026-10-01T00:00:00Z",
    )

    wire_client.create_task.assert_called_once_with(
        1, "X", "", priority=3, due_date="2026-10-01T00:00:00Z"
    )


# ---------------------------------------------------------------------------
# Assignees (opskit #396)
# ---------------------------------------------------------------------------

def test_assignee_is_resolved_and_attached(mod, wire_client):
    wire_client.list_projects.return_value = [{"id": 1, "title": "Tickets"}]
    wire_client.list_users.return_value = [{"id": 2, "username": "alice"}]
    wire_client.create_task.return_value = {"id": 9}

    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X", assignees="alice"))

    wire_client.list_users.assert_called_once_with("alice")
    wire_client.add_assignee.assert_called_once_with(9, 2)
    assert result["assigned"] == ["alice"]
    assert "warnings" not in result


def test_multiple_assignees_are_each_attached(mod, wire_client):
    wire_client.list_projects.return_value = [{"id": 1, "title": "Tickets"}]
    wire_client.list_users.side_effect = lambda q: (
        [{"id": 2, "username": "alice"}] if q == "alice" else [{"id": 3, "username": "bob"}]
    )
    wire_client.create_task.return_value = {"id": 10}

    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X", assignees="alice, bob"))

    assert wire_client.add_assignee.call_count == 2
    assert set(result["assigned"]) == {"alice", "bob"}


def test_unknown_assignee_returns_error_before_creating_task(mod, wire_client):
    wire_client.list_projects.return_value = [{"id": 1, "title": "Tickets"}]
    wire_client.list_users.return_value = []

    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X", assignees="ghost"))

    assert "error" in result
    assert "ghost" in result["error"]
    wire_client.create_task.assert_not_called()


# ---------------------------------------------------------------------------
# Labels (opskit #396)
# ---------------------------------------------------------------------------

def test_label_is_resolved_and_attached(mod, wire_client):
    wire_client.list_projects.return_value = [{"id": 1, "title": "Tickets"}]
    wire_client.list_labels.return_value = [{"id": 5, "title": "security"}]
    wire_client.create_task.return_value = {"id": 11}

    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X", labels="security"))

    wire_client.add_label.assert_called_once_with(11, 5)
    assert result["labeled"] == ["security"]


def test_label_with_incidental_whitespace_still_matches(mod, wire_client):
    # opskit #398: a real label was titled "security " (trailing space, a
    # data-entry accident) and a caller passing the sensible spelling
    # 'security' could never match it.
    wire_client.list_projects.return_value = [{"id": 1, "title": "Tickets"}]
    wire_client.list_labels.return_value = [{"id": 5, "title": "security "}]
    wire_client.create_task.return_value = {"id": 13}

    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X", labels="security"))

    wire_client.add_label.assert_called_once_with(13, 5)
    assert result["labeled"] == ["security "]


def test_no_matching_label_returns_error_before_creating_task(mod, wire_client):
    wire_client.list_projects.return_value = [{"id": 1, "title": "Tickets"}]
    wire_client.list_labels.return_value = [{"id": 5, "title": "security"}]

    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X", labels="ghost"))

    assert "error" in result
    wire_client.create_task.assert_not_called()


def test_ambiguous_label_returns_error_before_creating_task(mod, wire_client):
    wire_client.list_projects.return_value = [{"id": 1, "title": "Tickets"}]
    wire_client.list_labels.return_value = [
        {"id": 5, "title": "security"},
        {"id": 6, "title": "security"},
    ]

    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X", labels="security"))

    assert "error" in result
    wire_client.create_task.assert_not_called()


# ---------------------------------------------------------------------------
# Partial-attach failure -- task already exists, must not read as a bare error
# ---------------------------------------------------------------------------

def test_attach_failure_after_creation_is_a_warning_not_a_bare_error(mod, wire_client):
    wire_client.list_projects.return_value = [{"id": 1, "title": "Tickets"}]
    wire_client.list_users.return_value = [{"id": 2, "username": "alice"}]
    wire_client.create_task.return_value = {"id": 12}
    wire_client.add_assignee.side_effect = http_error(500, {"message": "boom"})

    result = json.loads(mod.vikunja_create_task(tenant=TENANT, title="X", assignees="alice"))

    assert "error" not in result
    assert result["url"] == f"{BASE_URL}/tasks/12"
    assert any("alice" in w and "boom" in w for w in result["warnings"])
