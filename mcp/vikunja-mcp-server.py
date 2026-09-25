#!/usr/bin/env python3
"""
Vikunja MCP Server — task creation in a Vikunja instance (opskit issue #393).

Tools:
  vikunja_create_task   Create a task in a project, resolved by name, and
                         report the task's URL

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

    def create_task(self, project_id, title: str, description: str) -> dict:
        # PUT, not POST -- POST 404s on this API.
        resp = self.session.put(
            f"{self.base_url}/api/v1/projects/{project_id}/tasks",
            json={"title": title, "description": description},
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


@mcp.tool()
def vikunja_create_task(
    tenant: str,
    title: str,
    description: str = "",
    project: str = None,
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
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"
    if not title or not title.strip():
        return json.dumps({"error": "title is required"})

    try:
        client = get_client(tenant)
        proj = _resolve_project(client, project, TENANTS[tenant].get("default_project"))
        result = client.create_task(proj["id"], title, description)
        base_url = TENANTS[tenant]["base_url"].rstrip("/")
        return json.dumps({
            "tenant": tenant,
            "task": result,
            "url": f"{base_url}/tasks/{result.get('id')}",
        }, indent=2)
    except (LookupError, ValueError, RuntimeError) as e:
        return json.dumps({"error": str(e)})
    except requests.HTTPError as e:
        try:
            body = e.response.json()
        except Exception:
            body = e.response.text if e.response is not None else str(e)
        status = e.response.status_code if e.response is not None else "?"
        return json.dumps({"error": f"Vikunja API error ({status}): {body}"})
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
