#!/usr/bin/env python3
"""
Vikunja MCP Server — task creation in a Vikunja instance (opskit issue #393).

Tools:
  vikunja_create_task   Create a task in a project, resolved by name, with
                         optional priority/due date/assignees/labels, and
                         report the task's URL (opskit issue #396)

Usage:
  python3 mcp/vikunja-mcp-server.py            # stdio MCP server
  python3 mcp/vikunja-mcp-server.py --test     # smoke-test the tool

Tenant configuration:
  Tenants are loaded from a gitignored mcp/tenants-vikunja.local.json (next
  to this script) if present; otherwise a single example tenant is used. The
  file maps tenant keys to {"base_url", "default_project", "description"}:

    {
      "client1": {
        "base_url": "https://vikunja.example.org",
        "default_project": "Tickets",
        "description": "Example client Vikunja instance"
      }
    }

  No real hostname, instance name, or project id belongs in this file when
  committed -- only in the gitignored copy (docs/client-data-policy.md).

  Set VIKUNJA_TENANTS_FILE to point at a different path instead of the
  default mcp/tenants-vikunja.local.json -- this is how the test suite stays
  independent of whatever (if anything) a developer has locally (same defect
  class as opskit issue #76).

Auth:
  Uses Vikunja's bearer-token auth (Authorization: Bearer <token>) against a
  token scoped to task-create + project-read only -- never a full
  personal-account token. Resolve it from the vault at runtime via
  mcp/vault-map.local.json + bin/mcp-run.sh; do not commit it
  (.opencode/rules/no-plaintext-creds.md).

Environment (or .env):
  Each tenant reads VIKUNJA_<TENANT_KEY_UPPERCASED>_TOKEN, e.g.:
  VIKUNJA_CLIENT1_TOKEN=<scoped API token for vikunja.example.org>
  # VIKUNJA_TOKEN=<token>   # fallback used for any tenant without its own var
"""

import json
import os
import sys
from pathlib import Path

import requests

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("ERROR: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).parent.parent.resolve()

# VIKUNJA_TENANTS_FILE lets a caller (notably the test suite) override the
# config path instead of always reading the developer's real, gitignored
# mcp/tenants-vikunja.local.json.
_TENANTS_FILE = (
    Path(os.environ["VIKUNJA_TENANTS_FILE"])
    if os.environ.get("VIKUNJA_TENANTS_FILE")
    else Path(__file__).parent / "tenants-vikunja.local.json"
)


def _load_tenants() -> dict:
    """Load tenant config from gitignored tenants-vikunja.local.json, else example fallback."""
    if _TENANTS_FILE.exists():
        return json.loads(_TENANTS_FILE.read_text())
    return {
        "client1": {
            "base_url": "https://vikunja.example.org",
            "default_project": "Tickets",
            "description": "Example client Vikunja instance",
        },
    }


TENANTS = _load_tenants()

mcp = FastMCP("vikunja")


def load_env():
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)


class VikunjaClient:
    """Talks to a Vikunja instance as a scoped API token -- no login call, no
    session cookie, no personal-account credential."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def list_projects(self) -> list:
        resp = self.session.get(f"{self.base_url}/api/v1/projects", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def list_users(self, query: str) -> list:
        # A substring search (opskit #396 verified live) -- callers must
        # filter to an exact 'username' match, never trust it as exact.
        resp = self.session.get(
            f"{self.base_url}/api/v1/users", params={"s": query}, timeout=15
        )
        resp.raise_for_status()
        return resp.json()

    def list_labels(self) -> list:
        resp = self.session.get(f"{self.base_url}/api/v1/labels", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def create_task(
        self,
        project_id,
        title: str,
        description: str,
        priority: int = None,
        due_date: str = None,
    ) -> dict:
        # PUT, not POST -- POST 404s on this API. priority/due_date are plain
        # fields on the create body (opskit #396 verified live) -- no
        # separate call needed, unlike assignees/labels below.
        body = {"title": title, "description": description}
        if priority is not None:
            body["priority"] = priority
        if due_date is not None:
            body["due_date"] = due_date
        resp = self.session.put(
            f"{self.base_url}/api/v1/projects/{project_id}/tasks",
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def add_assignee(self, task_id, user_id) -> dict:
        resp = self.session.put(
            f"{self.base_url}/api/v1/tasks/{task_id}/assignees",
            json={"user_id": user_id},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def add_label(self, task_id, label_id) -> dict:
        resp = self.session.put(
            f"{self.base_url}/api/v1/tasks/{task_id}/labels",
            json={"label_id": label_id},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


_clients: dict[str, VikunjaClient] = {}


def get_client(tenant: str) -> VikunjaClient:
    if tenant not in _clients:
        load_env()
        base_url = TENANTS[tenant]["base_url"]
        token_var = f"VIKUNJA_{tenant.upper()}_TOKEN"
        token = os.environ.get(token_var) or os.environ.get("VIKUNJA_TOKEN")
        if not token:
            raise RuntimeError(
                f"{token_var} (or VIKUNJA_TOKEN) not set. Resolve the scoped API "
                "token from the vault and export it (or add to .env) -- never "
                "commit it."
            )
        _clients[tenant] = VikunjaClient(base_url, token)
    return _clients[tenant]


def _resolve_project(client: VikunjaClient, project: str, default_project: str) -> dict:
    """Resolve a project by exact title match. Never guesses: zero or more
    than one match is an error naming the candidates, not a silent pick."""
    target = project or default_project
    if not target:
        raise ValueError(
            "no project given and this tenant has no default_project configured"
        )
    projects = client.list_projects()
    matches = [p for p in projects if p.get("title") == target]
    if not matches:
        available = ", ".join(p.get("title", "") for p in projects) or "(none)"
        raise LookupError(f"no project named '{target}' found. Available: {available}")
    if len(matches) > 1:
        ids = ", ".join(str(m.get("id")) for m in matches)
        raise LookupError(
            f"multiple projects named '{target}' found (ids: {ids}) -- "
            "rename one so the title is unique, or pass its id instead."
        )
    return matches[0]


def _resolve_users(client: VikunjaClient, assignees: str) -> list:
    """Resolve each comma-separated username to a user record by exact
    'username' match. Never guesses: no match is an error naming the
    username, before any task is created."""
    resolved = []
    for name in (n.strip() for n in assignees.split(",")):
        if not name:
            continue
        matches = [u for u in client.list_users(name) if u.get("username") == name]
        if not matches:
            raise LookupError(f"no user named '{name}' found")
        if len(matches) > 1:
            ids = ", ".join(str(m.get("id")) for m in matches)
            raise LookupError(f"multiple users named '{name}' found (ids: {ids})")
        resolved.append(matches[0])
    return resolved


def _resolve_labels(client: VikunjaClient, labels: str) -> list:
    """Resolve each comma-separated label name to a label record by exact
    title match. Zero or multiple matches is an error naming the
    candidates, same convention as _resolve_project -- never a guess.

    Matches against the label's *stripped* title (opskit #398): a live label
    was found titled "security " (trailing space, a data-entry accident),
    which made it unmatchable by the sensible spelling. Incidental
    leading/trailing whitespace in label data is never what meaningfully
    distinguishes two real labels, so it's tolerated here -- everything else
    about the "exact match, never guess" behavior is unchanged."""
    names = [n.strip() for n in labels.split(",") if n.strip()]
    if not names:
        return []
    all_labels = client.list_labels()
    resolved = []
    for name in names:
        matches = [label for label in all_labels if label.get("title", "").strip() == name]
        if not matches:
            available = ", ".join(label.get("title", "") for label in all_labels) or "(none)"
            raise LookupError(f"no label named '{name}' found. Available: {available}")
        if len(matches) > 1:
            ids = ", ".join(str(m.get("id")) for m in matches)
            raise LookupError(
                f"multiple labels named '{name}' found (ids: {ids}) -- "
                "rename one so the title is unique, or pass its id instead."
            )
        resolved.append(matches[0])
    return resolved


def _http_error_detail(e: requests.HTTPError) -> str:
    try:
        body = e.response.json()
    except Exception:
        body = e.response.text if e.response is not None else str(e)
    status = e.response.status_code if e.response is not None else "?"
    return f"{status}: {body}"


@mcp.tool()
def vikunja_create_task(
    tenant: str,
    title: str,
    description: str = "",
    project: str = None,
    priority: int = None,
    due_date: str = None,
    assignees: str = None,
    labels: str = None,
) -> str:
    """
    Create a task in a Vikunja project and report its URL.

    Args:
        tenant: Tenant name (e.g. 'client1'; see mcp/tenants-vikunja.local.json).
        title: Task title (required).
        description: Task description (optional).
        project: Project name to create the task in (optional -- falls back
            to the tenant's configured default_project). Zero or multiple
            matching projects is an error, never a guess.
        priority: 0=Unset, 1=Low, 2=Medium, 3=High, 4=Urgent, 5=DO NOW
            (optional).
        due_date: ISO8601 timestamp, e.g. '2026-10-01T00:00:00Z' (optional).
        assignees: Comma-separated usernames to assign (optional). Each must
            match an existing user's exact username; no match is an error,
            never a guess.
        labels: Comma-separated label names to attach (optional). Each must
            match an existing label's exact title; zero or multiple matches
            is an error, never a guess.
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"
    if not title or not title.strip():
        return json.dumps({"error": "title is required"})
    if priority is not None and not (0 <= priority <= 5):
        return json.dumps({"error": f"priority must be 0-5 (Unset..DO NOW), got {priority}"})

    try:
        client = get_client(tenant)
        proj = _resolve_project(client, project, TENANTS[tenant].get("default_project"))
        # Resolved before the task exists: a typo'd assignee/label name must
        # never leave a task half-configured (opskit #396).
        users = _resolve_users(client, assignees) if assignees else []
        label_objs = _resolve_labels(client, labels) if labels else []

        result = client.create_task(
            proj["id"], title, description, priority=priority, due_date=due_date
        )
        base_url = TENANTS[tenant]["base_url"].rstrip("/")
        task_id = result.get("id")

        # Attaching happens after creation (these endpoints need a real task
        # id) -- a failure here must not read as "nothing happened": the
        # task is real, so this stays a success envelope with a warning,
        # never a bare {"error": ...} that could prompt a duplicate retry.
        warnings = []
        assigned = []
        for user in users:
            try:
                client.add_assignee(task_id, user["id"])
                assigned.append(user["username"])
            except requests.HTTPError as e:
                warnings.append(f"created but failed to assign '{user['username']}': {_http_error_detail(e)}")

        labeled = []
        for label in label_objs:
            try:
                client.add_label(task_id, label["id"])
                labeled.append(label["title"])
            except requests.HTTPError as e:
                warnings.append(f"created but failed to attach label '{label['title']}': {_http_error_detail(e)}")

        out = {"tenant": tenant, "task": result, "url": f"{base_url}/tasks/{task_id}"}
        if assigned:
            out["assigned"] = assigned
        if labeled:
            out["labeled"] = labeled
        if warnings:
            out["warnings"] = warnings
        return json.dumps(out, indent=2)
    except (LookupError, ValueError, RuntimeError) as e:
        return json.dumps({"error": str(e)})
    except requests.HTTPError as e:
        return json.dumps({"error": f"Vikunja API error ({_http_error_detail(e)})"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def test_tools():
    load_env()
    tenant = next(iter(TENANTS))
    token_var = f"VIKUNJA_{tenant.upper()}_TOKEN"
    if not (os.environ.get(token_var) or os.environ.get("VIKUNJA_TOKEN")):
        print(f"No {token_var} (or VIKUNJA_TOKEN) set. Edit .env first.")
        sys.exit(1)

    print("=== Testing Vikunja MCP Tools ===\n")
    print(f"vikunja_create_task(tenant='{tenant}', title='MCP Test Task - please ignore')")
    print(vikunja_create_task(tenant=tenant, title="[TEST] MCP smoke test - please ignore"))
    print("\n=== Test complete ===")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test_tools()
    else:
        mcp.run(transport="stdio")
